"""
BigQuery schema for the staging table.

The staging table is the raw nine event columns *plus* four pipeline
metadata columns that record where each row came from. Keeping the
metadata means that later, if a batch turns out to be bad, we can find
and delete exactly its rows using `batch_id` or `source_file_name`.

`RAW_EVENT_SCHEMA` is just the first nine fields - the shape of the CSV
as it sits in GCS, before we bolt the metadata on.
"""

from google.cloud import bigquery

STAGING_SCHEMA = [
    # --- the raw event columns, straight from the source CSV --------------
    bigquery.SchemaField("event_time", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("event_type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("product_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("category_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("category_code", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("brand", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("price", "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("user_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("user_session", "STRING", mode="NULLABLE"),

    # --- pipeline metadata, added by this function -----------------------
    bigquery.SchemaField("ingestion_timestamp", "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("source_file_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("batch_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("load_type", "STRING", mode="NULLABLE"),
]

# The CSV in GCS only has the raw columns, so the temp load table uses
# just this slice. Index 9 == number of raw columns above.
RAW_EVENT_SCHEMA = STAGING_SCHEMA[:9]

# Column names in the same order, handy for building INSERT statements.
RAW_EVENT_COLUMNS = [field.name for field in RAW_EVENT_SCHEMA]
