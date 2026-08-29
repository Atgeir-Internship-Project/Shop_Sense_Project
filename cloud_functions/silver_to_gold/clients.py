"""
Shared GCP client for this function.

Gold is pure BigQuery orchestration - one client, reused across the warm
lifetime of the instance, created lazily so importing this module from a
unit test needs no credentials.
"""

from google.cloud import bigquery

_bq_client = None


def get_bigquery_client() -> bigquery.Client:
    """
    The one BigQuery client. Uses Application Default Credentials - on
    Cloud Functions that is the runtime service account, no key files.
    """
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client()
    return _bq_client
