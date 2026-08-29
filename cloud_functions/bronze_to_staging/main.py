"""
Cloud Function entrypoint for the second pipeline hop:

    Pub/Sub message from Bronze  ->  load rows into the staging table

Like the upstream function, this file is just the orchestration. Each
real step lives in its own module:

    message.py           - decode + vet the Pub/Sub message
    ingestion_control.py - idempotency / retry state machine
    tables.py            - make sure the staging table exists
    gcs.py               - confirm the GCS object hasn't changed under us
    staging_loader.py    - CSV -> temp table -> staging table
    pubsub_publisher.py  - announce the finished batch to staging_to_silver

The whole body runs inside one try/except/finally:
  - except : mark the batch FAILED and re-raise so Pub/Sub retries.
  - finally: always drop the temp table, success or failure.
"""

from datetime import datetime, timezone

import functions_framework

import ingestion_control
from gcs import verify_generation
from logger import get_logger
from message import SkipMessage, parse_message, resolve_load_type, validate_message
from pubsub_publisher import publish_staging_loaded
from staging_loader import (
    copy_temp_to_staging,
    drop_temp_table,
    load_csv_to_temp_table,
)
from tables import ensure_staging_table

logger = get_logger()


@functions_framework.cloud_event
def bronze_to_staging(cloud_event):
    """Runs once per 'bronze loaded' message from the upstream function."""

    logger.info("=" * 60)
    logger.info("Bronze -> Staging function started")

    # We need these in `except` / `finally` even if we fail early, so
    # declare them up front.
    batch_id = None
    temp_table_id = None

    try:
        # --- 1. Decode the message -------------------------------------
        message = parse_message(cloud_event)
        bucket_name = message["bucket_name"]
        file_name = message["file_name"]
        generation = message["generation"]
        batch_id = message["batch_id"]

        # --- 2. Is this message for us? -------------------------------
        try:
            validate_message(bucket_name, file_name)
        except SkipMessage as skip:
            logger.info(str(skip))
            return

        load_type = resolve_load_type(file_name)
        ingestion_timestamp = datetime.now(timezone.utc)
        logger.info(
            "Load type: %s | ingestion_timestamp: %s",
            load_type,
            ingestion_timestamp,
        )

        # --- 3. Duplicate delivery? ----------------------------------
        # If this exact (bucket, file, generation) already has a SUCCESS
        # row, Pub/Sub re-delivered a message we already handled. The load
        # is done, but re-announce it anyway: this is also the path a
        # message takes when a previous run loaded staging fine but then
        # failed on the publish below. staging_to_silver is idempotent, so
        # a redundant announcement is harmless.
        if ingestion_control.already_succeeded(
            bucket_name, file_name, generation
        ):
            logger.info("Duplicate message - staging load already done.")
            # row_count isn't re-derived on this path; Silver treats it as
            # informational only.
            publish_staging_loaded(
                batch_id=batch_id,
                source_file_name=file_name,
                load_type=load_type,
                row_count=None,
            )
            return

        # --- 4. Make sure the destination table exists --------------
        ensure_staging_table()

        # --- 5. Claim the batch -------------------------------------
        # Creates or resumes the PROCESSING record. If it comes back
        # SUCCESS, another run beat us to it and we're done.
        state = ingestion_control.start_processing(
            batch_id=batch_id,
            bucket_name=bucket_name,
            file_name=file_name,
            generation=generation,
            load_type=load_type,
            ingestion_timestamp=ingestion_timestamp,
        )
        if state == "SUCCESS":
            logger.info("Batch already processed successfully.")
            publish_staging_loaded(
                batch_id=batch_id,
                source_file_name=file_name,
                load_type=load_type,
                row_count=None,
            )
            return

        # --- 6. Confirm the file is unchanged ----------------------
        verify_generation(bucket_name, file_name, generation)
        gcs_uri = f"gs://{bucket_name}/{file_name}"

        # --- 7. CSV -> temp table --------------------------------
        temp_table_id, row_count = load_csv_to_temp_table(batch_id, gcs_uri)
        if row_count == 0:
            raise ValueError("CSV contains no data rows.")

        # --- 8. temp table -> staging (adds metadata) ------------
        copy_temp_to_staging(
            temp_table_id=temp_table_id,
            ingestion_timestamp=ingestion_timestamp,
            source_file_name=file_name,
            batch_id=batch_id,
            load_type=load_type,
        )

        # --- 9. Mark the batch done -----------------------------
        ingestion_control.finish(batch_id, "SUCCESS")

        # --- 10. Hand off to the Silver stage -------------------
        # Announce the finished batch so staging_to_silver can process
        # exactly these rows. A failure here re-raises; with --retry on the
        # deployment Pub/Sub redelivers, and step 3 (batch already SUCCESS)
        # re-sends this announcement without re-loading staging.
        publish_staging_loaded(
            batch_id=batch_id,
            source_file_name=file_name,
            load_type=load_type,
            row_count=row_count,
        )

        logger.info(
            "Bronze -> Staging done. rows=%s batch=%s load_type=%s",
            row_count,
            batch_id,
            load_type,
        )
        logger.info("=" * 60)

    except Exception as error:
        logger.error("Bronze -> Staging failed: %s", error)

        # Best-effort: flip the batch to FAILED so a retry knows to pick
        # it back up. Don't let a failure here mask the real error.
        if batch_id:
            try:
                ingestion_control.finish(batch_id, "FAILED")
            except Exception as control_error:  # noqa: BLE001
                logger.error(
                    "Could not mark batch %s FAILED: %s",
                    batch_id,
                    control_error,
                )

        # Re-raise so Cloud Functions records the failure and Pub/Sub
        # redelivers the message.
        raise

    finally:
        # The temp table is disposable and named per-batch, so clean it
        # up no matter how we got here.
        if temp_table_id:
            drop_temp_table(temp_table_id)
