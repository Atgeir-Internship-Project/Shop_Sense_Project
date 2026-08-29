"""
Decode and vet the incoming Pub/Sub message.

`bronze_to_staging` publishes a small JSON blob after it loads a batch
into the staging table. Pub/Sub wraps it in a CloudEvent envelope and
base64-encodes the body, so step one is to peel that off and get back a
plain dict with the fields we need.
"""

import base64
import json

from logger import get_logger

logger = get_logger()

# The fields bronze_to_staging promises to send. batch_id is the one we
# cannot work without - it selects the rows to transform.
_REQUIRED_FIELDS = ("batch_id", "source_file_name", "load_type")


class SkipMessage(Exception):
    """
    Raised when a message cannot or should not be processed.

    main.py catches it, logs a line and returns cleanly so Pub/Sub
    considers the message handled and does not redeliver it forever.
    """


def parse_message(cloud_event) -> dict:
    """
    Unwrap CloudEvent -> Pub/Sub envelope -> base64 -> JSON and return
    the batch fields.

    Raises SkipMessage if the envelope is malformed or a required field
    is missing - a message we can never make sense of should not be
    retried.
    """

    try:
        encoded = cloud_event.data["message"]["data"]
        decoded = base64.b64decode(encoded).decode("utf-8")
        body = json.loads(decoded)
    except (KeyError, ValueError, TypeError) as error:
        raise SkipMessage(f"Unreadable Pub/Sub message: {error}") from error

    logger.info("Received Pub/Sub message: %s", body)

    missing = [f for f in _REQUIRED_FIELDS if not body.get(f)]
    if missing:
        raise SkipMessage(
            f"Message is missing required field(s): {', '.join(missing)}"
        )

    return {
        "batch_id": str(body["batch_id"]),
        "source_file_name": str(body["source_file_name"]),
        "load_type": str(body["load_type"]),
        "row_count": body.get("row_count"),
    }
