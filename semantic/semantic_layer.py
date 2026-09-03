"""
ShopSense semantic layer.

Loads the metric / dimension catalog (``metrics.yaml``) and compiles a
structured request - metric names, dimension names, filters - into
deterministic, parameterised BigQuery Standard SQL against
``vw_semantic_events``.

The GenAI agent calls this instead of writing SQL:

  * it can only reference metric / dimension / segment names that exist in the
    catalog, so a question cannot invent a metric formula;
  * every filter value is bound as a BigQuery query parameter (``@p0`` ...),
    so a question cannot inject SQL through a value;
  * the metric maths lives in the catalog once, so the dashboard and the agent
    always return the same number.

Typical use::

    from semantic import SemanticLayer

    sl = SemanticLayer.load()
    q = sl.build_aggregate_query(
        metrics=["view_to_cart_rate", "views", "carts"],
        dimensions=["category"],
        filters=[{"field": "event_date", "op": "last_n_days", "value": 7}],
        order_by="view_to_cart_dropoff",
    )
    # q.sql          -> the SQL string
    # q.parameters   -> [{"name": "p0", "type": "INT64", "value": 7}]
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from typing import Any

import yaml

_CATALOG_PATH = pathlib.Path(__file__).with_name("metrics.yaml")

_FILTER_OPS = {"eq", "ne", "in", "gte", "lte", "between", "contains", "last_n_days"}

# dimension `type` in the catalog -> BigQuery scalar parameter type
_PARAM_TYPE = {
    "string": "STRING",
    "date": "DATE",
    "number": "INT64",
    "bool": "BOOL",
}

_SCALAR_SQL_OP = {"eq": "=", "ne": "!=", "gte": ">=", "lte": "<="}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SemanticLayerError(ValueError):
    """A request referenced something not in the catalog, or was malformed."""


@dataclasses.dataclass
class CompiledQuery:
    """A compiled query: the SQL text plus the parameters it expects.

    ``parameters`` is a list of ``{"name", "type", "value"}`` dicts. The caller
    turns each into a ``google.cloud.bigquery`` query parameter - a plain
    ``ScalarQueryParameter`` unless ``type`` starts with ``ARRAY<``.
    """

    sql: str
    parameters: list[dict[str, Any]]


class _ParamBag:
    """Accumulates query parameters and hands back ``@pN`` placeholders."""

    def __init__(self) -> None:
        self._params: list[dict[str, Any]] = []

    def add(self, value: Any, bq_type: str) -> str:
        name = f"p{len(self._params)}"
        self._params.append({"name": name, "type": bq_type, "value": value})
        return f"@{name}"

    def add_array(self, values: Any, element_type: str) -> str:
        name = f"p{len(self._params)}"
        self._params.append(
            {"name": name, "type": f"ARRAY<{element_type}>", "value": list(values)}
        )
        return f"@{name}"

    @property
    def params(self) -> list[dict[str, Any]]:
        return list(self._params)


class SemanticLayer:
    """The metric / dimension catalog plus the SQL builder."""

    def __init__(self, catalog: dict[str, Any]) -> None:
        self._catalog = catalog
        self.base_view: str = catalog["base_view"]
        self.metrics: dict[str, Any] = catalog.get("metrics", {})
        self.dimensions: dict[str, Any] = catalog.get("dimensions", {})
        self.time_grains: dict[str, str] = catalog.get("time_grains", {})
        self.segments: dict[str, Any] = catalog.get("segments", {})
        self._anchor: str = catalog.get("relative_date_anchor", "CURRENT_DATE()")
        self._default_limit = int(catalog.get("default_row_limit", 1000))
        self._max_limit = int(catalog.get("max_row_limit", 10000))

        self._validate_catalog()
        self._dim_lookup = self._build_lookup(self.dimensions)
        self._metric_lookup = self._build_lookup(self.metrics)

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, path: str | pathlib.Path | None = None) -> "SemanticLayer":
        target = pathlib.Path(path) if path else _CATALOG_PATH
        with open(target, "r", encoding="utf-8") as handle:
            return cls(yaml.safe_load(handle))

    def _validate_catalog(self) -> None:
        # Every catalog name becomes a SQL alias, so it must be a bare
        # identifier - this is the guard that lets build_* interpolate names
        # directly without escaping.
        for section, items in (
            ("metric", self.metrics),
            ("dimension", self.dimensions),
            ("time_grain", self.time_grains),
        ):
            for name in items:
                if not _IDENT_RE.match(name):
                    raise SemanticLayerError(
                        f"{section} name {name!r} is not a bare identifier"
                    )
        if not self.metrics:
            raise SemanticLayerError("catalog defines no metrics")

    @staticmethod
    def _build_lookup(section: dict[str, Any]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for name, spec in section.items():
            lookup[_norm(name)] = name
            for synonym in spec.get("synonyms") or []:
                lookup.setdefault(_norm(synonym), name)
        return lookup

    # -- name resolution -------------------------------------------------

    def resolve_metric(self, token: str) -> str:
        key = _norm(token)
        if key in self._metric_lookup:
            return self._metric_lookup[key]
        raise SemanticLayerError(
            f"unknown metric {token!r}; known metrics: {sorted(self.metrics)}"
        )

    def resolve_dimension(self, token: str) -> str:
        key = _norm(token)
        if key in self._dim_lookup:
            return self._dim_lookup[key]
        raise SemanticLayerError(
            f"unknown dimension {token!r}; known dimensions: {sorted(self.dimensions)}"
        )

    # -- agent-facing description --------------------------------------

    def describe(self) -> dict[str, Any]:
        """A compact, JSON-serialisable catalog for grounding the agent."""
        return {
            "base_view": self.base_view,
            "notes": (
                "Pick metric and dimension names from below. The data is "
                "historical (2019-10 / 2019-11); 'this week' / 'recently' means "
                "the last days present in the data."
            ),
            "metrics": {
                name: {
                    "label": spec["label"],
                    "type": spec.get("type"),
                    "description": _one_line(spec.get("description")),
                }
                for name, spec in self.metrics.items()
            },
            "dimensions": {
                name: {
                    "label": spec["label"],
                    "synonyms": list(spec.get("synonyms") or []),
                }
                for name, spec in self.dimensions.items()
            },
            "time_grains": sorted(self.time_grains),
            "segments": {
                name: {
                    "label": spec["label"],
                    "grain": spec["grain"],
                    "description": _one_line(spec.get("description")),
                }
                for name, spec in self.segments.items()
            },
        }

    # -- query building ------------------------------------------------

    def build_aggregate_query(
        self,
        metrics: list[str],
        dimensions: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        time_grain: str | None = None,
        order_by: str | None = None,
        descending: bool = True,
        limit: int | None = None,
    ) -> CompiledQuery:
        """Compile ``metrics`` sliced by ``dimensions`` / ``time_grain``."""
        if not metrics:
            raise SemanticLayerError("at least one metric is required")

        metric_names = _dedupe([self.resolve_metric(m) for m in metrics])
        dim_names = _dedupe([self.resolve_dimension(d) for d in (dimensions or [])])

        if time_grain is not None and time_grain not in self.time_grains:
            raise SemanticLayerError(
                f"unknown time_grain {time_grain!r}; known: {sorted(self.time_grains)}"
            )

        bag = _ParamBag()
        select_exprs: list[str] = []
        group_ordinals: list[int] = []

        if time_grain:
            select_exprs.append(f"{self.time_grains[time_grain]} AS {time_grain}")
            group_ordinals.append(len(select_exprs))

        for dim in dim_names:
            expr = self.dimensions[dim]["expr"]
            select_exprs.append(expr if expr == dim else f"{expr} AS {dim}")
            group_ordinals.append(len(select_exprs))

        for metric in metric_names:
            select_exprs.append(f"{self.metrics[metric]['expr']} AS {metric}")

        where_sql = self._compile_filters(filters or [], bag)

        lines = [
            "SELECT",
            "  " + ",\n  ".join(select_exprs),
            f"FROM `{self.base_view}`",
        ]
        if where_sql:
            lines.append(f"WHERE {where_sql}")
        if group_ordinals:
            lines.append("GROUP BY " + ", ".join(str(o) for o in group_ordinals))
            order_col = self._resolve_order(
                order_by, metric_names, dim_names, time_grain
            )
            lines.append(f"ORDER BY {order_col} {'DESC' if descending else 'ASC'}")

        lines.append(f"LIMIT {self._clamp_limit(limit)}")
        return CompiledQuery("\n".join(lines), bag.params)

    def build_segment_query(
        self,
        segment: str,
        metrics: list[str] | None = None,
        limit: int | None = None,
    ) -> CompiledQuery:
        """Compile an entity-grain segment (a population defined by ``HAVING``)."""
        if segment not in self.segments:
            raise SemanticLayerError(
                f"unknown segment {segment!r}; known: {sorted(self.segments)}"
            )
        spec = self.segments[segment]
        entity = spec["entity_column"]
        if not _IDENT_RE.match(entity):
            raise SemanticLayerError(f"segment entity_column {entity!r} is not an identifier")

        wanted = metrics if metrics is not None else spec.get("default_metrics") or []
        metric_names = _dedupe([self.resolve_metric(m) for m in wanted])

        select_exprs = [entity]
        select_exprs += [
            f"{self.metrics[m]['expr']} AS {m}" for m in metric_names
        ]

        lines = [
            "SELECT",
            "  " + ",\n  ".join(select_exprs),
            f"FROM `{self.base_view}`",
            f"WHERE {entity} IS NOT NULL",
            f"GROUP BY {entity}",
            f"HAVING {spec['having']}",
        ]
        if metric_names:
            lines.append(f"ORDER BY {metric_names[0]} DESC")
        lines.append(f"LIMIT {self._clamp_limit(limit)}")
        return CompiledQuery("\n".join(lines), [])

    # -- internals ---------------------------------------------------

    def _compile_filters(
        self, filters: list[dict[str, Any]], bag: _ParamBag
    ) -> str:
        clauses: list[str] = []
        for spec in filters:
            field = spec.get("field")
            op = str(spec.get("op", "eq")).lower()
            value = spec.get("value")
            if op not in _FILTER_OPS:
                raise SemanticLayerError(
                    f"unknown filter op {op!r}; supported: {sorted(_FILTER_OPS)}"
                )
            dim = self.resolve_dimension(field)
            dim_spec = self.dimensions[dim]
            expr = dim_spec["expr"]
            bq_type = _PARAM_TYPE.get(dim_spec.get("type", "string"), "STRING")

            if op == "last_n_days":
                if dim_spec.get("type") != "date":
                    raise SemanticLayerError(
                        "'last_n_days' is only valid on a date dimension"
                    )
                placeholder = bag.add(int(value), "INT64")
                clauses.append(
                    f"{expr} >= DATE_SUB({self._anchor}, INTERVAL {placeholder} DAY)"
                )
            elif op == "in":
                if not isinstance(value, (list, tuple)) or not value:
                    raise SemanticLayerError("'in' filter needs a non-empty list value")
                placeholder = bag.add_array(value, bq_type)
                clauses.append(f"{expr} IN UNNEST({placeholder})")
            elif op == "between":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise SemanticLayerError("'between' filter needs [low, high]")
                low = bag.add(value[0], bq_type)
                high = bag.add(value[1], bq_type)
                clauses.append(f"{expr} BETWEEN {low} AND {high}")
            elif op == "contains":
                placeholder = bag.add(str(value), "STRING")
                clauses.append(
                    f"LOWER({expr}) LIKE CONCAT('%', LOWER({placeholder}), '%')"
                )
            else:
                placeholder = bag.add(value, bq_type)
                clauses.append(f"{expr} {_SCALAR_SQL_OP[op]} {placeholder}")

        return " AND ".join(clauses)

    def _resolve_order(
        self,
        order_by: str | None,
        metric_names: list[str],
        dim_names: list[str],
        time_grain: str | None,
    ) -> str:
        if not order_by:
            return metric_names[0] if metric_names else (time_grain or dim_names[0])

        key = str(order_by).strip().lower()
        if key in {"time", "date", "trend"} and time_grain:
            return time_grain
        try:
            metric = self.resolve_metric(order_by)
            if metric in metric_names:
                return metric
        except SemanticLayerError:
            pass
        try:
            dim = self.resolve_dimension(order_by)
            if dim in dim_names:
                return dim
        except SemanticLayerError:
            pass
        raise SemanticLayerError(
            f"order_by {order_by!r} must be one of the selected metrics/dimensions"
        )

    def _clamp_limit(self, limit: int | None) -> int:
        if limit is None:
            return self._default_limit
        return max(1, min(int(limit), self._max_limit))


def _norm(token: str) -> str:
    """Loose match key: lower-case, and treat ``-``/``_``/space alike.

    So "conversion_rate", "conversion rate" and "Conversion-Rate" all match.
    """
    return " ".join(str(token).lower().replace("-", " ").replace("_", " ").split())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _one_line(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())
