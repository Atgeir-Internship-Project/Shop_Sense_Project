"""
Shared GCP client for this function.

Silver is pure BigQuery orchestration - one client, reused across the
warm lifetime of the instance. It is created lazily so importing this
module (e.g. from a unit test) does not require credentials.
"""

from google.cloud import bigquery
from google.cloud import pubsub_v1

_bq_client = None
_publisher_client = None


def get_bigquery_client() -> bigquery.Client:
    """
    The one BigQuery client. Uses Application Default Credentials - on
    Cloud Functions that is the runtime service account, no key files.
    """
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client


def get_publisher_client() -> pubsub_v1.PublisherClient:
    """Pub/Sub publisher - used once per run to announce the finished batch."""
    global _publisher_client
    if _publisher_client is None:
        _publisher_client = pubsub_v1.PublisherClient()
    return _publisher_client
