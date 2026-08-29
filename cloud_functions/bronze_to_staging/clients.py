"""
Shared GCP clients for this function.

A client sets up auth and connection pools, which is wasteful to redo on
every event. Cloud Function instances stay warm between invocations, so
we build each client once and reuse it. The module-level `_*_client`
variables are the cache: None until first use, then the live client.
"""

from google.cloud import bigquery
from google.cloud import pubsub_v1
from google.cloud import storage

_bq_client = None
_storage_client = None
_publisher_client = None


def get_bigquery_client() -> bigquery.Client:
    """BigQuery client - does nearly all the work in this function."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client


def get_storage_client() -> storage.Client:
    """
    Storage client - used only to re-check the GCS object's generation
    before we trust it (see gcs.py).
    """
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


def get_publisher_client() -> pubsub_v1.PublisherClient:
    """
    Pub/Sub publisher - used once at the end of a successful run to tell
    the downstream staging_to_silver function that a batch has landed in
    the staging table.
    """
    global _publisher_client
    if _publisher_client is None:
        _publisher_client = pubsub_v1.PublisherClient()
    return _publisher_client
