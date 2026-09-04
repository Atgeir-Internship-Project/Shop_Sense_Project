"""
Gold-layer table schemas, defined here in code.

Terraform creates the eight Gold tables but without column definitions
(same arrangement as Bronze and Silver), so the schema is owned here. It
is expressed as BigQuery DDL column blocks because that is how the tables
are actually created:

  * the six dimension / bridge tables are rebuilt every run with
    CREATE OR REPLACE TABLE <name> (<columns>) AS SELECT ... - the column
    block pins the schema, the SELECT fills it.
  * fact_events and ingestion_insight_control are created once with
    CREATE TABLE IF NOT EXISTS <name> (<columns>) [PARTITION/CLUSTER] and
    then only ever appended to (fact via MERGE, control via DML).

Star-schema notes:
  * every dimension key is a FARM_FINGERPRINT of its natural business
    value, so a rebuild always produces the identical key for the same
    input - that is what makes the full-rebuild dimensions idempotent.
  * dim_category is keyed purely by category_code (the full dotted path).
    category_id is deliberately absent from every dimension - it is not
    1:1 with category_code - and rides along in fact_events only as an
    informational passthrough, never a foreign key.
  * UNKNOWN members use key -1 (dim_category, dim_brand). fact_events maps
    NULL category_code / brand to -1.
"""

from google.cloud import bigquery

# ---------------------------------------------------------------------------
# dim_date - one row per calendar day in the event_time range
# ---------------------------------------------------------------------------
DIM_DATE_COLUMNS = """
    date_key     DATE,
    day          INT64,
    week         INT64,
    month        INT64,
    month_name   STRING,
    quarter      INT64,
    year         INT64,
    day_of_week  STRING,
    is_weekend   BOOL
"""

# ---------------------------------------------------------------------------
# dim_category - keyed by category_code only (never category_id)
# ---------------------------------------------------------------------------
DIM_CATEGORY_COLUMNS = """
    category_key         INT64,
    category_name        STRING,
    category_code        STRING,
    parent_category_key  INT64,
    level_number         INT64,
    is_leaf              BOOL
"""

# ---------------------------------------------------------------------------
# bridge_category_hierarchy - closure table over dim_category
# ---------------------------------------------------------------------------
BRIDGE_CATEGORY_COLUMNS = """
    ancestor_category_key    INT64,
    descendant_category_key  INT64,
    hierarchy_level          INT64
"""

# ---------------------------------------------------------------------------
# dim_brand
# ---------------------------------------------------------------------------
DIM_BRAND_COLUMNS = """
    brand_key  INT64,
    brand      STRING
"""

# ---------------------------------------------------------------------------
# dim_product - SCD Type 1 (overwrite), one row per product_id
# ---------------------------------------------------------------------------
DIM_PRODUCT_COLUMNS = """
    product_key   INT64,
    product_id    INT64,
    category_key  INT64,
    brand_key     INT64
"""

# ---------------------------------------------------------------------------
# dim_session - one row per user_session, with rollups
# ---------------------------------------------------------------------------
DIM_SESSION_COLUMNS = """
    session_key          INT64,
    user_session         STRING,
    session_start_time   TIMESTAMP,
    session_end_time     TIMESTAMP,
    event_count          INT64,
    has_purchase         BOOL,
    is_multi_user        BOOL
"""

# ---------------------------------------------------------------------------
# fact_events - one row per Silver event, keyed on Silver's surrogate key.
# Created via the BigQuery client (tables.py), because it needs
# partitioning + clustering, which CREATE TABLE IF NOT EXISTS cannot add to
# a table Terraform already made.
# ---------------------------------------------------------------------------
FACT_EVENTS_SCHEMA = [
    bigquery.SchemaField("event_key", "STRING"),
    bigquery.SchemaField("event_time", "TIMESTAMP"),
    bigquery.SchemaField("date_key", "DATE"),
    bigquery.SchemaField("event_type", "STRING"),
    bigquery.SchemaField("product_key", "INT64"),
    bigquery.SchemaField("category_key", "INT64"),
    bigquery.SchemaField("brand_key", "INT64"),
    bigquery.SchemaField("session_key", "INT64"),
    bigquery.SchemaField("user_id", "INT64"),
    bigquery.SchemaField("category_id", "INT64"),
    bigquery.SchemaField("price", "FLOAT64"),
    bigquery.SchemaField("event_count", "INT64"),
    bigquery.SchemaField("is_view", "INT64"),
    bigquery.SchemaField("is_cart", "INT64"),
    bigquery.SchemaField("is_purchase", "INT64"),
    bigquery.SchemaField("batch_id", "STRING"),
    bigquery.SchemaField("gold_loaded_at", "TIMESTAMP"),
]
FACT_EVENTS_PARTITION_FIELD = "date_key"
FACT_EVENTS_CLUSTER_FIELDS = ["category_key", "product_key", "session_key"]

# ---------------------------------------------------------------------------
# ingestion_insight_control - mirrors the Silver control table's state
# machine (batch_id key, PROCESSING -> SUCCESS / FAILED) plus Gold metrics
# ---------------------------------------------------------------------------
CONTROL_SCHEMA = [
    bigquery.SchemaField("batch_id", "STRING"),
    bigquery.SchemaField("source_file_name", "STRING"),
    bigquery.SchemaField("load_type", "STRING"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("ingestion_timestamp", "TIMESTAMP"),
    bigquery.SchemaField("silver_rows", "INT64"),
    bigquery.SchemaField("dim_date_rows", "INT64"),
    bigquery.SchemaField("dim_category_rows", "INT64"),
    bigquery.SchemaField("bridge_category_hierarchy_rows", "INT64"),
    bigquery.SchemaField("dim_brand_rows", "INT64"),
    bigquery.SchemaField("dim_product_rows", "INT64"),
    bigquery.SchemaField("dim_session_rows", "INT64"),
    bigquery.SchemaField("fact_events_inserted", "INT64"),
    bigquery.SchemaField("fact_events_total", "INT64"),
    bigquery.SchemaField("fk_resolution_failures", "INT64"),
    bigquery.SchemaField("duplicate_event_keys", "INT64"),
    bigquery.SchemaField("bq_job_id", "STRING"),
]

# Metric columns written on SUCCESS, in a fixed order so control.py's
# UPDATE and its parameter list cannot drift apart.
METRIC_COLUMNS = (
    "silver_rows",
    "dim_date_rows",
    "dim_category_rows",
    "bridge_category_hierarchy_rows",
    "dim_brand_rows",
    "dim_product_rows",
    "dim_session_rows",
    "fact_events_inserted",
    "fact_events_total",
    "fk_resolution_failures",
    "duplicate_event_keys",
    "bq_job_id",
)
