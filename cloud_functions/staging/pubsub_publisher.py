"""
Tell the next stage that a staging load just finished.

Mirror of the same module in `gcs_to_bronze`: this function's work ends
with a Pub/Sub message that the `staging_to_silver` function is
subscribed to. We send along the batch identity so the Silver function
knows exactly which rows in the staging table to process and never has
to scan the whole table.
"""

import json

from clients import get_bigquery_client, get_publisher_client
from config import STAGING_LOADED_TOPIC
from logger import get_logger

logger = get_logger()


def publish_staging_loaded(
    batch_id: str,
    source_file_name: str,
    load_type: str,
    row_count: int,
) -> str:
    """
    Publish the "staging loaded" event and return the Pub/Sub message id.

    The body is plain UTF-8 JSON (Pub/Sub payloads are raw bytes).
    `future.result()` blocks until the publish is confirmed, so if Pub/Sub
    is unreachable we fail here rather than "succeeding" with nothing
    downstream. The staging load itself is idempotent on batch_id, so a
    redelivery caused by a failure here is safe.
    """

    publisher = get_publisher_client()

    # The topic lives in the same project as our BigQuery client.
    project = get_bigquery_client().project
    topic_path = publisher.topic_path(project, STAGING_LOADED_TOPIC)

    message = {
        "batch_id": batch_id,
        "source_file_name": source_file_name,
        "load_type": load_type,
        "row_count": row_count,
    }

    logger.info("Publishing message to %s: %s", topic_path, message)

    future = publisher.publish(
        topic_path, json.dumps(message).encode("utf-8")
    )
    message_id = future.result()

    logger.info("Pub/Sub message published. Message ID: %s", message_id)

    return message_id
