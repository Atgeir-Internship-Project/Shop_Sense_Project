"""
Decoding and vetting the incoming Pub/Sub message.

The upstream `gcs_to_bronze` function publishes a small JSON blob after it
loads a file into Bronze. Pub/Sub wraps that in an envelope and
base64-encodes the body, so step one is to peel all that off and get back
to a plain dict.
"""

import base64
import json

from config import BUCKET_NAME
from logger import get_logger

logger = get_logger()


class SkipMessage(Exception):
    """
    Raised when a message should be ignored (wrong bucket, not a CSV).

    Like `SkipFile` upstream, this is a normal outcome - main.py catches
    it, logs, and returns so Pub/Sub considers the message handled.
    """


def parse_message(cloud_event) -> dict:
    """
    Unwrap the CloudEvent -> Pub/Sub envelope -> base64 -> JSON, and
    return just the fields we use downstream.

    `generation` is forced to str so comparisons against the string we
    read back from GCS and BigQuery are apples-to-apples.
    """

    encoded = cloud_event.data["message"]["data"]
    decoded = base64.b64decode(encoded).decode("utf-8")
    body = json.loads(decoded)

    logger.info("Received Pub/Sub message: %s", body)

    return {
        "bucket_name": body["bucket_name"],
        "file_name": body["file_name"],
        "generation": str(body["generation"]),
        "batch_id": body["batch_id"],
    }


def validate_message(bucket_name: str, file_name: str) -> None:
    """Guard clause - skip anything that isn't a CSV in our bucket."""

    if bucket_name != BUCKET_NAME:
        raise SkipMessage(f"Ignoring unexpected bucket: {bucket_name}")

    if not file_name.lower().endswith(".csv"):
        raise SkipMessage(f"Skipping non-CSV file: {file_name}")


def resolve_load_type(file_name: str) -> str:
    """
    Same folder-prefix convention as upstream: `historical/` for
    backfills, `incremental/` for routine deltas, else UNKNOWN. We
    recompute it here rather than trusting the message so the two
    functions can't disagree.
    """

    if file_name.startswith("historical/"):
        return "HISTORICAL"

    if file_name.startswith("incremental/"):
        return "INCREMENTAL"

    return "UNKNOWN"
