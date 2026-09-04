"""
Cloud Function entrypoint for the first pipeline hop:

    CSV lands in GCS  ->  load into Bronze  ->  announce it on Pub/Sub

This file is intentionally thin. It reads top-to-bottom like a summary of
the pipeline; each real step lives in its own module:

    gcs_event.py        - understand and vet the incoming event
    bronze_loader.py    - GCS CSV  ->  Bronze BigQuery table
    pubsub_publisher.py - notify the downstream staging function
"""

import functions_framework

from bronze_loader import get_blob_size, load_csv_to_bronze
from gcs_event import (
    SkipFile,
    parse_event,
    resolve_load_type,
    validate_event,
)
from logger import get_logger
from pubsub_publisher import publish_bronze_loaded

logger = get_logger()


@functions_framework.cloud_event
def gcs_to_bronze(cloud_event):
    """Runs once per file uploaded to the ShopSense data-lake bucket."""

    # --- 1. What just landed? --------------------------------------------
    event = parse_event(cloud_event)
    bucket_name = event["bucket_name"]
    file_name = event["file_name"]
    generation = event["generation"]

    logger.info(
        "New file detected: gs://%s/%s (generation=%s)",
        bucket_name,
        file_name,
        generation,
    )

    # --- 2. Is it something we should process? ---------------------------
    # validate_event raises SkipFile for anything that isn't a CSV in our
    # bucket. That's a normal outcome, not a failure, so we just log and
    # return - the event gets acked and won't be redelivered.
    try:
        validate_event(bucket_name, file_name)
    except SkipFile as skip:
        logger.info(str(skip))
        return

    logger.info(
        "File size: %s bytes", get_blob_size(bucket_name, file_name)
    )

    # --- 3. Load the raw rows into Bronze --------------------------------
    row_count = load_csv_to_bronze(bucket_name, file_name)

    # --- 4. Build the batch identity ------------------------------------
    # load_type comes from the folder prefix (historical/ vs incremental/).
    # batch_id is derived from the GCS generation so it's unique per
    # upload and reproducible - the staging function keys its
    # idempotency / retry logic off this same value.
    load_type = resolve_load_type(file_name)
    batch_id = f"BATCH_{generation}"
    logger.info("Load type: %s | Batch ID: %s", load_type, batch_id)

    # --- 5. Hand off to the next stage --------------------------------
    publish_bronze_loaded(
        bucket_name=bucket_name,
        file_name=file_name,
        generation=generation,
        batch_id=batch_id,
        load_type=load_type,
        row_count=row_count,
    )

    logger.info("GCS -> Bronze -> Pub/Sub completed successfully.")