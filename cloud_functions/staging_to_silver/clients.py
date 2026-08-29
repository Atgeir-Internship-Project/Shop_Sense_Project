"""
Shared GCP client for this function.

Silver is pure BigQuery orchestration - one client, reused across the
warm lifetime of the instance. It is created lazily so importing this
module (e.g. from a unit test) does not require credentials.
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
