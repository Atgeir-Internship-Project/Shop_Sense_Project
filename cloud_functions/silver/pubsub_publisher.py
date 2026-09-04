"""
Announce a finished Silver load to the Gold stage.

Mirror of the same module in gcs_to_bronze / bronze_to_staging: once this
function has loaded a batch into the Silver table it publishes a small
JSON message that silver_to_gold is subscribed to. We forward the batch
identity so Gold has the same lineage the rest of the pipeline carries.
"""

import json

from clients import get_bigquery_client, get_publisher_client
from config import SILVER_LOADED_TOPIC
from logger import get_logger

logger = get_logger()


def publish_silver_loaded(
    batch_id: str,
    source_file_name: str,
    load_type: str,
) -> str:
    """
    Publish the "silver loaded" event and return the Pub/Sub message id.

    `future.result()` blocks until the publish is confirmed so a transient
    Pub/Sub failure surfaces here rather than silently skipping the Gold
    handoff. The Silver load is idempotent on batch_id, so a redelivery
    caused by a failure here is safe.
    """

    publisher = get_publisher_client()
    project = get_bigquery_client().project
    topic_path = publisher.topic_path(project, SILVER_LOADED_TOPIC)

    message = {
        "batch_id": batch_id,
        "source_file_name": source_file_name,
        "load_type": load_type,
    }

    logger.info("Publishing message to %s: %s", topic_path, message)

    future = publisher.publish(
        topic_path, json.dumps(message).encode("utf-8")
    )
    message_id = future.result()

    logger.info("Pub/Sub message published. Message ID: %s", message_id)
    return message_id
