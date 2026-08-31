"""
Submit the Gold build script to BigQuery and read back the run metrics.

One multi-statement job does the whole layer (see gold_sql.py). Its final
statement is a single-row SELECT of counts and integrity checks, which is
all that flows back into Python - no table data.
"""

from clients import get_bigquery_client
from gold_sql import build_gold_sql
from logger import get_logger

logger = get_logger()

_METRIC_KEYS = (
    "silver_rows",
    "dim_date_rows",
    "dim_category_rows",
    "bridge_category_hierarchy_rows",
    "dim_brand_rows",
    "dim_product_rows",
    "dim_session_rows",
    "fact_events_inserted",
    "fact_events_total",
    "fk_resolution_failures",
    "duplicate_event_keys",
)


def run_gold_build() -> tuple[str, dict]:
    """
    Run the Gold build. Returns (bq_job_id, metrics).

    Raises on any BigQuery failure - the dimension rebuilds and the fact
    MERGE are each individually safe to retry, so a later run recovers.
    """

    client = get_bigquery_client()
    sql = build_gold_sql()

    logger.info("Submitting Gold build script")
    query_job = client.query(sql)

    rows = list(query_job.result())  # blocks; last statement = metrics SELECT
    job_id = query_job.job_id

    if not rows:
        raise RuntimeError(f"Gold build {job_id} returned no metrics row.")

    row = rows[0]
    metrics = {key: row[key] for key in _METRIC_KEYS}

    logger.info("Gold build job %s finished: %s", job_id, metrics)
    return job_id, metrics
