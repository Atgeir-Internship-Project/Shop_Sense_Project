"""
Tools the ShopSense agent may call.

These are plain functions (Google ADK wraps them into FunctionTools from their
type hints + docstrings). They never let the model write SQL: the model passes
metric / dimension / filter *names*, and the semantic layer compiles the SQL.

Importing this module does not require google-adk or google-cloud-bigquery -
only the semantic layer. The BigQuery client is created lazily on first query.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# The semantic layer package lives at the repo root.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from semantic import SemanticLayer, SemanticLayerError  # noqa: E402

from .bigquery_runner import BigQueryRunner, BigQueryRunnerError  # noqa: E402

# --- lazily-built singletons (overridable in tests via configure) ---------
_semantic_layer: SemanticLayer | None = None
_runner: BigQueryRunner | None = None


def configure(
    semantic_layer: SemanticLayer | None = None,
    runner: BigQueryRunner | None = None,
) -> None:
    """Inject a catalog / query runner (tests use this; production uses defaults)."""
    global _semantic_layer, _runner
    if semantic_layer is not None:
        _semantic_layer = semantic_layer
    if runner is not None:
        _runner = runner


def _sl() -> SemanticLayer:
    global _semantic_layer
    if _semantic_layer is None:
        _semantic_layer = SemanticLayer.load()
    return _semantic_layer


def _bq() -> BigQueryRunner:
    global _runner
    if _runner is None:
        _runner = BigQueryRunner()
    return _runner


# --- helpers -----------------------------------------------------------

def _as_list(value: Any) -> list:
    """Forgiving coercion - the model sometimes sends a string or JSON text."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                return list(json.loads(text))
            except json.JSONDecodeError:
                pass
        return [part.strip() for part in text.split(",") if part.strip()]
    return [value]


def _normalise_filters(filters: Any) -> list[dict]:
    items = filters
    if isinstance(filters, str) and filters.strip():
        try:
            items = json.loads(filters)
        except json.JSONDecodeError:
            raise SemanticLayerError(f"could not parse filters: {filters!r}")
    if items in (None, ""):
        return []
    if isinstance(items, dict):
        items = [items]
    return list(items)


# --- tools -----------------------------------------------------------

def get_semantic_catalog() -> dict:
    """List every metric, dimension, time grain and segment the analyst can use.

    Call this once at the start of a conversation. The returned `metrics` and
    `dimensions` keys are the ONLY names accepted by `run_metric_query`.
    """
    return _sl().describe()


def explain_metric(name: str) -> dict:
    """Return the exact definition (formula + business meaning) of one metric.

    Use this when the user asks how a number is calculated.
    """
    try:
        canonical = _sl().resolve_metric(name)
    except SemanticLayerError as exc:
        return {"error": str(exc)}
    spec = _sl().metrics[canonical]
    return {
        "metric": canonical,
        "label": spec.get("label"),
        "formula": spec.get("expr"),
        "type": spec.get("type"),
        "description": " ".join(str(spec.get("description", "")).split()),
    }


def run_metric_query(
    metrics: list[str],
    dimensions: list[str] = None,
    filters: list[dict] = None,
    time_grain: str = "",
    order_by: str = "",
    descending: bool = True,
    limit: int = 25,
) -> dict:
    """Aggregate one or more metrics, optionally sliced by dimensions / time.

    metrics:    metric names from get_semantic_catalog, e.g. ["revenue", "conversion_rate"].
    dimensions: dimension names to break the result down by (GROUP BY),
                e.g. ["category"] or ["category_l1"].
    filters:    list of {"field": <dimension>, "op": <op>, "value": <value>}.
                ops: "eq", "ne", "in" (value is a list), "gte", "lte",
                "between" (value is [low, high]), "contains", "last_n_days"
                (value is an integer number of days, field must be "event_date").
                Example - Electronics only, last 7 days of data:
                [{"field": "category_l1", "op": "eq", "value": "electronics"},
                 {"field": "event_date", "op": "last_n_days", "value": 7}]
    time_grain: "" (none), "day", "week", "month" or "quarter" - adds a
                trend column. Use for "daily / weekly / monthly" questions.
    order_by:   a selected metric or dimension name to sort by (default: the
                first metric). Use "time" with a time_grain to sort chronologically.
    descending: sort direction (default True).
    limit:      max rows to return (capped by the semantic layer).

    Returns {"sql", "row_count", "rows", "metrics_used"} or {"error"}.
    """
    try:
        compiled = _sl().build_aggregate_query(
            metrics=_as_list(metrics),
            dimensions=_as_list(dimensions),
            filters=_normalise_filters(filters),
            time_grain=time_grain or None,
            order_by=order_by or None,
            descending=bool(descending),
            limit=int(limit) if limit else None,
        )
    except (SemanticLayerError, ValueError) as exc:
        return {"error": str(exc)}

    return _execute(compiled, metrics=_as_list(metrics))


def run_segment_query(
    segment: str,
    metrics: list[str] = None,
    limit: int = 50,
) -> dict:
    """Query a named population that needs a HAVING clause.

    segment: a segment name from get_semantic_catalog, e.g.
             "high_intent_never_purchase" (users with >=1 cart and 0 purchases).
    metrics: metric names to report per entity (default: the segment's own set).
    limit:   max rows.

    Returns {"sql", "row_count", "rows"} or {"error"}.
    """
    try:
        compiled = _sl().build_segment_query(
            segment=segment,
            metrics=_as_list(metrics) or None,
            limit=int(limit) if limit else None,
        )
    except (SemanticLayerError, ValueError) as exc:
        return {"error": str(exc)}

    return _execute(compiled)


def _execute(compiled: Any, metrics: list[str] | None = None) -> dict:
    try:
        result = _bq().execute(compiled)
    except BigQueryRunnerError as exc:
        return {"error": f"query failed: {exc}", "sql": compiled.sql}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not run query: {exc}", "sql": compiled.sql}
    if metrics:
        result["metrics_used"] = [_sl().resolve_metric(m) for m in metrics]
    return result
