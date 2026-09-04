"""
Tell the next stage that a Bronze load just finished.

This function's whole job ends with a Pub/Sub message. The
`bronze_to_staging` function is subscribed to the topic and picks up from
here. We send along everything it needs so it doesn't have to re-inspect
the file: which object, which version, the batch id, the load type and
how many rows we loaded.
"""

import json

from clients import get_bigquery_client, get_publisher_client
from config import PUBSUB_TOPIC
from logger import get_logger

logger = get_logger()


def publish_bronze_loaded(
    bucket_name: str,
    file_name: str,
    generation: str,
    batch_id: str,
    load_type: str,
    row_count: int,
) -> str:
    """
    Publish the "bronze loaded" event and return the Pub/Sub message id.

    The message body is plain JSON, UTF-8 encoded (Pub/Sub payloads are
    raw bytes). `future.result()` waits for the publish to be confirmed
    so that if Pub/Sub is unreachable we find out here and fail loudly,
    rather than the function "succeeding" with nothing downstream.
    """

    publisher = get_publisher_client()

    # The topic lives in the same project as our BigQuery client.
    project = get_bigquery_client().project
    topic_path = publisher.topic_path(project, PUBSUB_TOPIC)

    message = {
        "bucket_name": bucket_name,
        "file_name": file_name,
        "generation": generation,
        "batch_id": batch_id,
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
