"""
The actual work: get the CSV from GCS into the Bronze BigQuery table.

Key idea: we never download the file into the function. We hand BigQuery
the `gs://` URI and let it stream the CSV in directly. That keeps memory
usage flat no matter how large the file is.
"""

from google.cloud import bigquery

from clients import get_bigquery_client, get_storage_client
from config import BIGQUERY_DATASET, BRONZE_TABLE
from logger import get_logger
from schemas import BRONZE_SCHEMA

logger = get_logger()


def get_blob_size(bucket_name: str, file_name: str) -> int:
    """
    Return the object's size in bytes.

    Purely for logging/visibility - it lets us see at a glance in the
    logs whether a 10 KB test file or a 2 GB backfill just landed.
    `blob.reload()` is what actually fetches the metadata from GCS.
    """

    blob = get_storage_client().bucket(bucket_name).blob(file_name)
    blob.reload()
    return blob.size


def load_csv_to_bronze(bucket_name: str, file_name: str) -> int:
    """
    Load one CSV file into the Bronze table and return the row count.

    Everything about *how* to read the file is in `job_config`:
      - CSV source, skip the 1 header row.
      - Use our fixed BRONZE_SCHEMA rather than autodetect, so the column
        types never drift between files.
      - WRITE_APPEND: Bronze is an ever-growing history, we add to it, we
        never overwrite it. Deduplication happens further downstream.
    """

    bq_client = get_bigquery_client()

    # Fully-qualified name: project.dataset.table
    table_id = f"{bq_client.project}.{BIGQUERY_DATASET}.{BRONZE_TABLE}"
    gcs_uri = f"gs://{bucket_name}/{file_name}"

    logger.info("Loading %s into Bronze table %s", gcs_uri, table_id)

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=BRONZE_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    # Kick off the load job, then block until BigQuery finishes it.
    # `.result()` also raises if the job failed, which we want - a failed
    # load should fail the whole function so the event is retried.
    load_job = bq_client.load_table_from_uri(
        gcs_uri, table_id, job_config=job_config
    )
    load_job.result()

    logger.info(
        "Bronze load successful. Rows loaded: %s", load_job.output_rows
    )

    return load_job.output_rows
