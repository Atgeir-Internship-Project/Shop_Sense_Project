"""
The ingestion_insight_control table: how Gold stays safe to retry.

Same design as ingestion_transform_control in the Silver dataset. Every
batch that triggers a Gold build gets one row moving through a small
state machine:

    (new) -> PROCESSING -> SUCCESS
                 ^  |
                 |  v
               FAILED  (a later retry flips it back to PROCESSING)

`batch_id` is the key and comes straight from the Pub/Sub message. On
SUCCESS the run metrics are stamped onto the row.
"""

from google.cloud import bigquery

from clients import get_bigquery_client
from config import control_table_id
from logger import get_logger
from schemas import METRIC_COLUMNS

logger = get_logger()


def already_succeeded(batch_id: str) -> bool:
    """True if this batch already has a SUCCESS row - a duplicate delivery."""

    sql = f"""
        SELECT status
        FROM `{control_table_id()}`
        WHERE batch_id = @batch_id
          AND status = 'SUCCESS'
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)
        ]
    )
    rows = list(
        get_bigquery_client().query(sql, job_config=job_config).result()
    )
    return bool(rows)


def start_processing(
    batch_id: str,
    source_file_name: str,
    load_type: str,
    ingestion_timestamp,
) -> str:
    """
    Claim the batch and report the state it was in: "SUCCESS" (already
    done, stop) or "PROCESSING" (ours to run).
    """

    client = get_bigquery_client()
    table_id = control_table_id()

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
                bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
            ]
        )
        client.query(update_sql, job_config=update_config).result()
        logger.info("Batch %s changed %s -> PROCESSING.", batch_id, status)
        return "PROCESSING"

    insert_sql = f"""
        INSERT INTO `{table_id}`
        (batch_id, source_file_name, load_type, status, ingestion_timestamp)
        VALUES
        (@batch_id, @source_file_name, @load_type, 'PROCESSING',
         @ingestion_timestamp)
    """
    insert_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
            bigquery.ScalarQueryParameter(
                "source_file_name", "STRING", source_file_name
            ),
            bigquery.ScalarQueryParameter("load_type", "STRING", load_type),
            bigquery.ScalarQueryParameter(
                "ingestion_timestamp", "TIMESTAMP", ingestion_timestamp
            ),
        ]
    )
    client.query(insert_sql, job_config=insert_config).result()
    logger.info("Insight control record created: %s -> PROCESSING", batch_id)
    return "PROCESSING"


def finish_success(batch_id: str, metrics: dict) -> None:
    """Move the batch PROCESSING -> SUCCESS and record its metrics."""

    client = get_bigquery_client()

    set_clause = ", ".join(f"{col} = @{col}" for col in METRIC_COLUMNS)
    sql = f"""
        UPDATE `{control_table_id()}`
        SET status = 'SUCCESS', {set_clause}
        WHERE batch_id = @batch_id
          AND status = 'PROCESSING'
    """

    params = [bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)]
    for col in METRIC_COLUMNS:
        bq_type = "STRING" if col == "bq_job_id" else "INT64"
        params.append(
            bigquery.ScalarQueryParameter(col, bq_type, metrics.get(col))
        )

    job = client.query(
        sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
    )
    job.result()

    if job.num_dml_affected_rows == 0:
        raise RuntimeError(
            f"No PROCESSING record for batch_id={batch_id}; "
            f"could not mark SUCCESS."
        )
    logger.info("Batch %s marked SUCCESS.", batch_id)


def finish_failed(batch_id: str, bq_job_id: str | None = None) -> None:
    """
    Best-effort flip PROCESSING -> FAILED. Never raises - it runs inside
    the error handler.
    """

    client = get_bigquery_client()
    sql = f"""
        UPDATE `{control_table_id()}`
        SET status = 'FAILED', bq_job_id = @bq_job_id
        WHERE batch_id = @batch_id
          AND status = 'PROCESSING'
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("bq_job_id", "STRING", bq_job_id),
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
        ]
    )
    client.query(sql, job_config=job_config).result()
    logger.info("Batch %s marked FAILED.", batch_id)
