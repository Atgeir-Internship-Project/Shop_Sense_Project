"""
Executes a semantic-layer CompiledQuery against BigQuery.

Kept separate from the ADK tools so it can be swapped for a fake in tests and
so importing the tools does not require google-cloud-bigquery to be installed.
"""

from __future__ import annotations

import datetime
import decimal
import logging
import os
from typing import Any

_log = logging.getLogger("shopsense.bigquery")


class BigQueryRunnerError(RuntimeError):
    """A query failed to validate or execute."""


def _jsonify(value: Any) -> Any:
    """Make a BigQuery cell safe to hand back to the model as JSON."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    return value


class BigQueryRunner:
    """Thin wrapper over the BigQuery client for parameterised SELECTs."""

    def __init__(
        self,
        project: str | None = None,
        location: str | None = None,
        client: Any | None = None,
        dry_run_first: bool = True,
        max_rows: int = 200,
    ) -> None:
        self._project = project or os.environ.get(
            "SHOPSENSE_BQ_PROJECT", "shop-sense-project"
        )
        self._location = location or os.environ.get(
            "SHOPSENSE_BQ_LOCATION", "asia-south1"
        )
        self._client = client
        self._dry_run_first = dry_run_first
        self._max_rows = max_rows

    # -- client ---------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import bigquery  # lazy - not needed for tests

            self._client = bigquery.Client(
                project=self._project, location=self._location
            )
        return self._client

    @staticmethod
    def _to_bq_parameters(parameters: list[dict[str, Any]]) -> list[Any]:
        from google.cloud import bigquery

        out = []
        for param in parameters:
            bq_type = param["type"]
            if bq_type.startswith("ARRAY<"):
                out.append(
                    bigquery.ArrayQueryParameter(
                        param["name"], bq_type[len("ARRAY<") : -1], param["value"]
                    )
                )
            else:
                out.append(
                    bigquery.ScalarQueryParameter(
                        param["name"], bq_type, param["value"]
                    )
                )
        return out

    # -- execution ----------------------------------------------------

    def execute(self, compiled: Any) -> dict[str, Any]:
        """Validate (dry run) then run ``compiled``; return rows + metadata."""
        from google.cloud import bigquery

        client = self._get_client()
        params = self._to_bq_parameters(compiled.parameters)

        try:
            if self._dry_run_first:
                _log.info("dry-run validating query (%d params)", len(params))
                client.query(
                    compiled.sql,
                    job_config=bigquery.QueryJobConfig(
                        query_parameters=params,
                        dry_run=True,
                        use_query_cache=False,
                    ),
                )
            _log.info("executing query")
            result = client.query(
                compiled.sql,
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result(max_results=self._max_rows)
        except Exception as exc:  # noqa: BLE001 - surface a clean message
            _log.warning("query failed: %s", exc)
            raise BigQueryRunnerError(str(exc)) from exc

        rows = [
            {key: _jsonify(val) for key, val in dict(row).items()} for row in result
        ]
        _log.info("query returned %d row(s)", len(rows))
        return {
            "sql": compiled.sql,
            "row_count": len(rows),
            "rows": rows,
            "truncated": len(rows) >= self._max_rows,
        }
