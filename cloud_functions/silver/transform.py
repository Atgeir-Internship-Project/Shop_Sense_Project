"""
Submit the Silver script to BigQuery and read back the run metrics.

This is the only place the function talks to BigQuery for the actual
transformation. It sends one script (see silver_sql.py), blocks on it,
and returns `(job_id, metrics)`. The metrics come from the script's final
SELECT - a single row - so no data volume flows through Python.
"""

from google.cloud import bigquery

from clients import get_bigquery_client
from logger import get_logger
from silver_sql import build_transform_sql

logger = get_logger()


def run_transformation(batch_id: str, loaded_at) -> tuple[str, dict]:
    """
    Run the Silver script for one batch.

    `loaded_at` is a timezone-aware datetime stamped onto every Silver
    and quarantine row this run produces. Returns the BigQuery job id and
    a metrics dict with keys:

        source_rows, exact_duplicates_removed, price_zero_removed,
        session_missing_removed, invalid_timestamp_rows, rows_inserted,
        rows_skipped
    """

    client = get_bigquery_client()
    sql = build_transform_sql()

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
            bigquery.ScalarQueryParameter("loaded_at", "TIMESTAMP", loaded_at),
        ]
    )

    logger.info("Submitting Silver transform for batch %s", batch_id)
    query_job = client.query(sql, job_config=job_config)

    # Blocks until the whole script finishes; raises on any failure, which
    # (thanks to the transaction) means Silver was left untouched. For a
    # multi-statement script, result() yields the rows of the last
    # statement - here the metrics SELECT.
    rows = list(query_job.result())
    job_id = query_job.job_id

    if not rows:
        raise RuntimeError(
            f"Silver script {job_id} returned no metrics row "
            f"(batch {batch_id})."
        )

    row = rows[0]
    merge_candidates = row["merge_candidates"]
    rows_inserted = row["rows_inserted"]

    metrics = {
        "source_rows": row["source_rows"],
        "exact_duplicates_removed": row["exact_duplicates_removed"],
        "price_zero_removed": row["price_zero_removed"],
        "session_missing_removed": row["session_missing_removed"],
        "invalid_timestamp_rows": row["invalid_timestamp_rows"],
        "rows_inserted": rows_inserted,
        # candidates that the MERGE found already present in Silver
        "rows_skipped": merge_candidates - rows_inserted,
    }

    logger.info("Silver transform job %s finished: %s", job_id, metrics)
    return job_id, metrics
