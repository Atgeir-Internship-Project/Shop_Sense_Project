"""
The ingestion_control table: how this function stays safe to retry.

Pub/Sub delivers "at least once", so the same message can arrive twice.
And a batch can fail halfway. To cope with both, every batch gets one row
in `ingestion_control` that moves through a tiny state machine:

    (new)  ->  PROCESSING  ->  SUCCESS
                   ^  |
                   |  v
                 FAILED  (a later retry flips it back to PROCESSING)

`batch_id` is the key. It's derived from the GCS object generation
upstream, so re-processing the same file always lands on the same row.
"""

from google.cloud import bigquery

from clients import get_bigquery_client
from config import INGESTION_CONTROL_TABLE
from logger import get_logger
from tables import get_table_id

logger = get_logger()


def _control_table_id() -> str:
    """`project.dataset.ingestion_control`."""
    return get_table_id(INGESTION_CONTROL_TABLE)


def already_succeeded(bucket_name: str, file_name: str, generation: str) -> bool:
    """
    Has this *exact* object version already been loaded successfully?

    Identity is the triple (bucket, file, generation). If we find a
    SUCCESS row for it, this is a duplicate Pub/Sub delivery and the
    caller should just stop.
    """

    query = f"""
        SELECT status
        FROM `{_control_table_id()}`
        WHERE bucket_name = @bucket_name
          AND file_name = @file_name
          AND generation = @generation
          AND status = 'SUCCESS'
        ORDER BY ingestion_timestamp DESC
        LIMIT 1
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("bucket_name", "STRING", bucket_name),
            bigquery.ScalarQueryParameter("file_name", "STRING", file_name),
            bigquery.ScalarQueryParameter("generation", "STRING", generation),
        ]
    )

    rows = list(
        get_bigquery_client().query(query, job_config=job_config).result()
    )

    if rows:
        logger.info(
            "This exact GCS object generation has already been processed."
        )
        return True

    return False


def start_processing(
    batch_id: str,
    bucket_name: str,
    file_name: str,
    generation: str,
    load_type: str,
    ingestion_timestamp,
) -> str:
    """
    Claim the batch for processing and report what state it was in.

    Returns one of:
      "SUCCESS"    - already done, caller should stop.
      "PROCESSING" - it's ours to run (freshly created, resumed, or a
                     retry of a previously FAILED batch).

    We look at the most recent row for this batch_id and branch:
      - SUCCESS      -> return "SUCCESS", do nothing.
      - PROCESSING   -> reuse the existing row (a concurrent / retried run).
      - FAILED       -> flip it back to PROCESSING and retry.
      - no row yet   -> INSERT a fresh PROCESSING row.

    We use DML INSERT (not the streaming API) so the row is immediately
    visible to the UPDATE that marks it SUCCESS/FAILED later.
    """

    client = get_bigquery_client()
    table_id = _control_table_id()

    # What's the latest status for this batch, if any?
    check_sql = f"""
        SELECT status
        FROM `{table_id}`
        WHERE batch_id = @batch_id
        ORDER BY ingestion_timestamp DESC
        LIMIT 1
    """
    check_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)
        ]
    )
    existing = list(client.query(check_sql, job_config=check_config).result())

    if existing:
        status = existing[0].status

        if status == "SUCCESS":
            logger.info("Batch %s already SUCCESS.", batch_id)
            return "SUCCESS"

        if status == "PROCESSING":
            logger.info(
                "Batch %s already PROCESSING - reusing that record.", batch_id
            )
            return "PROCESSING"

        if status == "FAILED":
            update_sql = f"""
                UPDATE `{table_id}`
                SET status = 'PROCESSING',
                    ingestion_timestamp = @ingestion_timestamp
                WHERE batch_id = @batch_id
            """
            update_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(
                        "ingestion_timestamp", "TIMESTAMP", ingestion_timestamp
                    ),
                    bigquery.ScalarQueryParameter(
                        "batch_id", "STRING", batch_id
                    ),
                ]
            )
            client.query(update_sql, job_config=update_config).result()
            logger.info("Batch %s changed FAILED -> PROCESSING.", batch_id)
            return "PROCESSING"

    # No row yet: create one.
    insert_sql = f"""
        INSERT INTO `{table_id}`
        (batch_id, bucket_name, file_name, generation, load_type,
         status, ingestion_timestamp)
        VALUES
        (@batch_id, @bucket_name, @file_name, @generation, @load_type,
         'PROCESSING', @ingestion_timestamp)
    """
    insert_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
            bigquery.ScalarQueryParameter("bucket_name", "STRING", bucket_name),
            bigquery.ScalarQueryParameter("file_name", "STRING", file_name),
            bigquery.ScalarQueryParameter("generation", "STRING", generation),
            bigquery.ScalarQueryParameter("load_type", "STRING", load_type),
            bigquery.ScalarQueryParameter(
                "ingestion_timestamp", "TIMESTAMP", ingestion_timestamp
            ),
        ]
    )
    client.query(insert_sql, job_config=insert_config).result()
    logger.info("Ingestion control record created: %s -> PROCESSING", batch_id)
    return "PROCESSING"


def finish(batch_id: str, status: str) -> None:
    """
    Close out the batch: PROCESSING -> SUCCESS (or -> FAILED).

    The WHERE clause pins `status = 'PROCESSING'` so we only ever move a
    row that we actually own. If nothing was updated, something is wrong
    with our assumptions (no PROCESSING row) and we raise rather than
    silently carry on.
    """

    client = get_bigquery_client()

    sql = f"""
        UPDATE `{_control_table_id()}`
        SET status = @status
        WHERE batch_id = @batch_id
          AND status = 'PROCESSING'
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
        ]
    )

    query_job = client.query(sql, job_config=job_config)
    query_job.result()

    if query_job.num_dml_affected_rows == 0:
        raise RuntimeError(
            f"No PROCESSING record found for batch_id={batch_id}; "
            f"could not set status to {status}."
        )

    logger.info("Batch %s marked as %s.", batch_id, status)
