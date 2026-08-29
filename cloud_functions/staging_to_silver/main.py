"""
Cloud Function entrypoint for the third pipeline hop:

    Pub/Sub message from staging  ->  clean + dedupe  ->  Silver table

Like the upstream functions, this file is only orchestration. Each real
step lives in its own module:

    message.py          - decode + vet the Pub/Sub message
    control.py          - ingestion_transform_control state machine + metrics
    tables.py           - make sure the 3 Silver-dataset tables exist
    silver_sql.py       - the BigQuery script that does the transformation
    transform.py        - submit that script and read back the metrics
    pubsub_publisher.py - announce the finished batch to silver_to_gold

The heavy lifting (cleaning, exact-duplicate removal, row hashing,
quarantine, surrogate keys, MERGE) all happens inside BigQuery. This
function never materialises batch data in memory - it submits SQL and
reads a single row of counts.
"""

from datetime import datetime, timezone

import functions_framework

import control
from logger import get_logger
from message import SkipMessage, parse_message
from pubsub_publisher import publish_silver_loaded
from tables import ensure_silver_tables
from transform import run_transformation

logger = get_logger()


@functions_framework.cloud_event
def staging_to_silver(cloud_event):
    """Runs once per 'staging loaded' message from bronze_to_staging."""

    logger.info("=" * 60)
    logger.info("Staging -> Silver function started")

    batch_id = None
    job_id = None

    try:
        # --- 1. Decode the message ------------------------------------
        try:
            message = parse_message(cloud_event)
        except SkipMessage as skip:
            logger.info(str(skip))
            return

        batch_id = message["batch_id"]
        source_file_name = message["source_file_name"]
        load_type = message["load_type"]
        logger.info(
            "Batch %s | file %s | load_type %s",
            batch_id,
            source_file_name,
            load_type,
        )

        # --- 2. Make sure the destination tables exist -------------
        # Done first: the control-table query in step 3 needs the table's
        # schema to be in place. Terraform may create these tables empty
        # (no columns), so ensure_silver_tables() also backfills columns.
        ensure_silver_tables()

        # --- 3. Duplicate delivery? ---------------------------------
        # Already done - but still re-announce to Gold. This is also the
        # path taken when a previous run loaded Silver fine but then failed
        # on the publish below; silver_to_gold is idempotent so a repeat
        # announcement is harmless.
        if control.already_succeeded(batch_id):
            logger.info("Duplicate message - Silver load already done.")
            publish_silver_loaded(batch_id, source_file_name, load_type)
            return

        # --- 4. Claim the batch -----------------------------------
        state = control.start_processing(
            batch_id=batch_id,
            source_file_name=source_file_name,
            load_type=load_type,
            ingestion_timestamp=datetime.now(timezone.utc),
        )
        if state == "SUCCESS":
            logger.info("Batch already processed successfully.")
            publish_silver_loaded(batch_id, source_file_name, load_type)
            return

        # --- 5. Run the transformation ---------------------------
        loaded_at = datetime.now(timezone.utc)
        job_id, metrics = run_transformation(batch_id, loaded_at)
        metrics["bq_job_id"] = job_id

        # --- 6. Mark the batch done + record metrics -----------
        control.finish_success(batch_id, metrics)

        # --- 7. Hand off to the Gold stage --------------------
        publish_silver_loaded(batch_id, source_file_name, load_type)

        logger.info(
            "Staging -> Silver done. batch=%s file=%s load_type=%s "
            "source_rows=%s exact_duplicates_removed=%s price_zero_removed=%s "
            "session_missing_removed=%s invalid_timestamp_rows=%s "
            "rows_inserted=%s rows_skipped=%s bq_job_id=%s status=SUCCESS",
            batch_id,
            source_file_name,
            load_type,
            metrics["source_rows"],
            metrics["exact_duplicates_removed"],
            metrics["price_zero_removed"],
            metrics["session_missing_removed"],
            metrics["invalid_timestamp_rows"],
            metrics["rows_inserted"],
            metrics["rows_skipped"],
            job_id,
        )
        logger.info("=" * 60)

    except Exception as error:
        logger.error("Staging -> Silver failed: %s", error)

        # Best-effort: flip the batch to FAILED so a retry picks it back
        # up. The transformation runs in a BigQuery transaction, so a
        # failure there left Silver and quarantine untouched.
        if batch_id:
            try:
                control.finish_failed(batch_id, job_id)
            except Exception as control_error:  # noqa: BLE001
                logger.error(
                    "Could not mark batch %s FAILED: %s",
                    batch_id,
                    control_error,
                )

        # Re-raise so Cloud Functions records the failure. Whether the
        # message is redelivered depends on the deployment's --retry flag.
        raise
