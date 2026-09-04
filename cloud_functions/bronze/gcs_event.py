"""
Everything about *understanding the incoming GCS event*.

When a file is uploaded to the data-lake bucket, GCS sends this function a
CloudEvent. This module turns that raw event into the few facts we
actually care about, and decides whether the file is one we should
process at all.
"""

from config import BUCKET_NAME, SUPPORTED_FILE_FORMAT


class SkipFile(Exception):
    """
    Raised when a file should be ignored.

    This is *not* an error - it just means "this upload isn't for us"
    (wrong bucket, not a CSV, etc). main.py catches it, logs a line and
    returns cleanly so the event is acknowledged and never retried.
    """


def parse_event(cloud_event) -> dict:
    """
    Pull the three things we need out of the CloudEvent payload.

    - bucket_name / file_name: where the object lives.
    - generation: GCS's version number for this exact upload. If the same
      path is overwritten later it gets a new generation, so we carry it
      downstream to tell one upload apart from another.
    """

    data = cloud_event.data

    return {
        "bucket_name": data["bucket"],
        "file_name": data["name"],
        "generation": str(data["generation"]),  # str so it survives JSON later
    }


def validate_event(bucket_name: str, file_name: str) -> None:
    """
    Guard clause: raise SkipFile unless this is a CSV in our bucket.

    The bucket check is defensive - the trigger should only ever fire for
    our bucket, but it's cheap to be sure. The extension check keeps out
    stray files (READMEs, .json manifests, folder placeholder objects).
    """

    if bucket_name != BUCKET_NAME:
        raise SkipFile(f"Ignoring unexpected bucket: {bucket_name}")

    if not file_name.lower().endswith(SUPPORTED_FILE_FORMAT):
        raise SkipFile(f"Skipping non-CSV file: {file_name}")


def resolve_load_type(file_name: str) -> str:
    """
    Work out whether this is a one-time backfill or a routine delta.

    We use a simple convention: files are uploaded under a `historical/`
    or `incremental/` prefix. The staging function later uses this label
    to decide how to treat the batch. Anything else is "UNKNOWN" so it
    still flows through but is easy to spot.
    """

    if file_name.startswith("historical/"):
        return "HISTORICAL"

    if file_name.startswith("incremental/"):
        return "INCREMENTAL"

    return "UNKNOWN"
