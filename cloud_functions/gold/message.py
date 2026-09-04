"""
Decode and vet the incoming Pub/Sub message.

staging_to_silver publishes a small JSON blob after it loads a batch into
the Silver table. Pub/Sub wraps it in a CloudEvent envelope and
base64-encodes the body; this module peels that back to a plain dict.

Note: Gold rebuilds its dimensions from the whole Silver table and MERGEs
the whole table into fact_events every run, so the batch fields are used
only for lineage and for the control-table key - not to filter Silver.
"""

import base64
import json

from logger import get_logger

logger = get_logger()

_REQUIRED_FIELDS = ("batch_id", "source_file_name", "load_type")


class SkipMessage(Exception):
    """
    Raised when a message cannot or should not be processed. main.py logs
    it and returns cleanly so Pub/Sub stops redelivering.
    """


def parse_message(cloud_event) -> dict:
    """Unwrap CloudEvent -> Pub/Sub envelope -> base64 -> JSON."""

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
    }
