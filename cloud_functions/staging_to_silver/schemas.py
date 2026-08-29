"""
BigQuery schemas for the three Silver-dataset tables, plus the one piece
of shared knowledge the transformation SQL is built from: the ordered
list of cleaned business columns that make up a record's identity.

Terraform owns the "real" table definitions. These schemas exist so the
function can create or repair a table on the fly (see tables.py) if a
deploy-ordering problem means a table isn't there yet. Nothing here ever
drops a table or a column.

`ROW_HASH_COLUMNS` is the contract for `row_hash`: the exact fields, in
the exact order, that are fed into SHA256. Changing this list changes
every hash, so it must not be touched without a full Silver rebuild.
"""

from google.cloud import bigquery

# ---------------------------------------------------------------------------
# The cleaned business columns, in hash order. Two cleaned records with the
# same values for all of these are "exact duplicates" and collapse to one
# Silver row. surrogate_key is deliberately NOT in this list.
# ---------------------------------------------------------------------------
ROW_HASH_COLUMNS = [
    "event_time",
    "event_type",
    "product_id",
    "category_id",
    "category_code",
    "brand",
    "price",
    "user_id",
    "user_session",
]


# ---------------------------------------------------------------------------
# transform_data_table  (Silver)
# ---------------------------------------------------------------------------
# surrogate_key and user_session are logically NOT NULL - the transform
# guarantees it. They are declared REQUIRED only when this code creates the
# table itself; columns added to a pre-existing table are always appended
# as NULLABLE (BigQuery cannot add a REQUIRED column to an existing table).
SILVER_SCHEMA = [
    bigquery.SchemaField("surrogate_key", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("row_hash", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("event_time", "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("event_type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("product_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("category_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("category_code", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("brand", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("price", "NUMERIC", mode="NULLABLE"),
    bigquery.SchemaField("user_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("user_session", "STRING", mode="REQUIRED"),
    # --- lineage: which batch first wrote this row, and when -------------
    bigquery.SchemaField("batch_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("silver_loaded_at", "TIMESTAMP", mode="NULLABLE"),
]


# ---------------------------------------------------------------------------
# quarantine_data_table
# ---------------------------------------------------------------------------
# The raw staging record, preserved exactly as it arrived (raw STRING
# event_time, raw FLOAT64 price), plus why and when it was quarantined.
QUARANTINE_SCHEMA = [
    bigquery.SchemaField("event_time", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("event_type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("product_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("category_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("category_code", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("brand", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("price", "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("user_id", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("user_session", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("ingestion_timestamp", "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("source_file_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("batch_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("load_type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("quarantine_reason", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("quarantined_at", "TIMESTAMP", mode="NULLABLE"),
]


# ---------------------------------------------------------------------------
# ingestion_transform_control
# ---------------------------------------------------------------------------
# Mirrors ingestion_control in the Bronze dataset (batch_id key, status
# state machine), with the per-run metrics the pipeline is required to
# record for every batch.
CONTROL_SCHEMA = [
    bigquery.SchemaField("batch_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("source_file_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("load_type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("status", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("ingestion_timestamp", "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("source_rows", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("exact_duplicates_removed", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("price_zero_removed", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("session_missing_removed", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("invalid_timestamp_rows", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("rows_inserted", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("rows_skipped", "INT64", mode="NULLABLE"),
    bigquery.SchemaField("bq_job_id", "STRING", mode="NULLABLE"),
]
