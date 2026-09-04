"""
One job: make sure the file we're about to load is the file the message
told us about.

Between the upstream function publishing its message and us picking it
up, someone could have overwritten the object at the same path. Each
overwrite gets a new GCS "generation" number, so we re-fetch the object
pinned to the exact generation from the message and confirm it still
matches. If it doesn't, we bail out instead of loading the wrong data.
"""

from clients import get_storage_client
from logger import get_logger

logger = get_logger()


def verify_generation(bucket_name: str, file_name: str, generation: str):
    """
    Return the GCS blob for this exact generation, or raise.

    `bucket.blob(name, generation=...)` asks GCS for that specific
    version. `blob.reload()` then fetches its metadata - if the version
    is gone, this raises NotFound; if it's there, we double-check the
    generation matches and return the blob (the caller uses its size for
    logging).
    """

    blob = get_storage_client().bucket(bucket_name).blob(
        file_name, generation=int(generation)
    )
    blob.reload()

    actual = str(blob.generation)
    logger.info(
        "Generation check - message: %s, current in GCS: %s",
        generation,
        actual,
    )

    if actual != generation:
        raise RuntimeError(
            f"GCS object generation changed. "
            f"Expected {generation}, found {actual}."
        )

    logger.info(
        "Verified gs://%s/%s (%s bytes)", bucket_name, file_name, blob.size
    )
    return blob
