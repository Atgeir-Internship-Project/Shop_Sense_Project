"""
Shared GCP client objects.

Building a BigQuery / Storage / Pub-Sub client is not free - it sets up
auth, HTTP sessions and connection pools. A Cloud Function instance
usually stays warm and handles many events in a row, so we create each
client once and hand the same instance back on every call.

The module-level `_*_client` variables act as a simple cache. They start
as None and are filled in the first time someone asks for that client.
"""

from google.cloud import bigquery
from google.cloud import pubsub_v1
from google.cloud import storage

_bq_client = None
_storage_client = None
_publisher_client = None


def get_bigquery_client() -> bigquery.Client:
    """BigQuery client used for loading data into the Bronze table."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client


def get_storage_client() -> storage.Client:
    """Storage client - we only use it to read object metadata (file size)."""
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


def get_publisher_client() -> pubsub_v1.PublisherClient:
    """Pub/Sub publisher for notifying the downstream staging function."""
    global _publisher_client
    if _publisher_client is None:
        _publisher_client = pubsub_v1.PublisherClient()
    return _publisher_client
