"""
The core load: GCS CSV  ->  temp table  ->  staging table.

Why the two-step dance with a temp table?
  - The CSV only has the nine raw columns. The staging table also has
    four metadata columns (ingestion_timestamp, source_file_name,
    batch_id, load_type).
  - So we let BigQuery bulk-load the CSV into a throwaway table that
    matches the CSV exactly (fast, no per-row Python), then run a single
    `INSERT ... SELECT` that copies those rows into staging while
    stamping the metadata on with query parameters.
  - The temp table is always cleaned up afterwards (see main.py's
    `finally`).

The CSV is never pulled into function memory - BigQuery reads it straight
from `gs://`.
"""

import re

from google.cloud import bigquery

from clients import get_bigquery_client
from config import STAGING_TABLE
from logger import get_logger
from schemas import RAW_EVENT_COLUMNS, RAW_EVENT_SCHEMA
from tables import get_table_id

logger = get_logger()


def _temp_table_id(batch_id: str) -> str:
    """
    Derive a valid, collision-free temp table name from the batch id.

    BigQuery table names only allow letters, digits and underscores, so
    we scrub anything else out of the batch id first.
    """

    safe = re.sub(r"[^a-zA-Z0-9_]", "_", batch_id)
    return get_table_id(f"_bronze_stg_temp_{safe}")


def load_csv_to_temp_table(batch_id: str, gcs_uri: str) -> tuple[str, int]:
    """
    Create the temp table and bulk-load the CSV into it.

    Returns `(temp_table_id, rows_loaded)`. We drop any leftover temp
    table from a previous failed run first, then load with:
      - skip_leading_rows=1  : ignore the header.
      - RAW_EVENT_SCHEMA     : fixed types, no autodetect drift.
      - allow_quoted_newlines: some category/brand values contain them.
    """

    client = get_bigquery_client()
    temp_table_id = _temp_table_id(batch_id)

    # Start from a clean slate in case a previous run died mid-way.
    client.delete_table(temp_table_id, not_found_ok=True)
    client.create_table(bigquery.Table(temp_table_id, schema=RAW_EVENT_SCHEMA))
    logger.info("Created temp table: %s", temp_table_id)

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=RAW_EVENT_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        allow_quoted_newlines=True,
    )

    logger.info("Loading CSV from %s into temp table", gcs_uri)
    load_job = client.load_table_from_uri(
        gcs_uri, temp_table_id, job_config=job_config
    )
    load_job.result()  # blocks; raises if the load failed

    logger.info("Rows loaded into temp table: %s", load_job.output_rows)
    return temp_table_id, load_job.output_rows


def copy_temp_to_staging(
    temp_table_id: str,
    ingestion_timestamp,
    source_file_name: str,
    batch_id: str,
    load_type: str,
) -> None:
    """
    Move rows from the temp table into staging, adding the metadata.

    One `INSERT ... SELECT`: the nine raw columns come from the temp
    table as-is, and the four metadata values are passed in as query
    parameters so the same literal is written to every row.
    """

    client = get_bigquery_client()
    staging_table_id = get_table_id(STAGING_TABLE)

    # "event_time,\n event_type,\n ..." - reused in both the column list
    # and the SELECT so they can never fall out of sync.
    raw_cols = ",\n            ".join(RAW_EVENT_COLUMNS)

    sql = f"""
        INSERT INTO `{staging_table_id}`
        (
            {raw_cols},
            ingestion_timestamp,
            source_file_name,
            batch_id,
            load_type
        )
        SELECT
            {raw_cols},
            @ingestion_timestamp,
            @source_file_name,
            @batch_id,
            @load_type
        FROM `{temp_table_id}`
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "ingestion_timestamp", "TIMESTAMP", ingestion_timestamp
            ),
            bigquery.ScalarQueryParameter(
                "source_file_name", "STRING", source_file_name
            ),
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
            bigquery.ScalarQueryParameter("load_type", "STRING", load_type),
        ]
    )

    logger.info("Inserting rows into staging: %s", staging_table_id)
    client.query(sql, job_config=job_config).result()
    logger.info("Temp table -> staging complete.")


def drop_temp_table(temp_table_id: str) -> None:
    """
    Delete the temp table. Best-effort: a leftover temp table is
    annoying but not fatal, and the next run for the same batch would
    recreate it anyway, so we only warn on failure.
    """

    try:
        get_bigquery_client().delete_table(temp_table_id, not_found_ok=True)
        logger.info("Temp table deleted: %s", temp_table_id)
    except Exception as error:  # noqa: BLE001 - deliberately swallow
        logger.warning(
            "Could not delete temp table %s: %s", temp_table_id, error
        )
