"""
Central configuration for the silver_to_gold Cloud Function.

Same pattern as the sibling functions: plain module-level constants, no
secrets, with environment-variable overrides for the values that might
differ between a local test project and production. deploy.ps1 references
the same names, so the two must be kept in step.
"""

import os

# --- GCP placement -------------------------------------------------------
PROJECT_ID = os.environ.get("PROJECT_ID", "shop-sense-project")
REGION = os.environ.get("REGION", "asia-south1")

# --- Source: the Silver table (written by staging_to_silver) ------------
# Already cleaned, type-cast and row-level deduplicated. Gold reads the
# whole table every run - the dimensions are deterministic rebuilds and
# the fact load is an idempotent MERGE.
SILVER_DATASET = os.environ.get("SILVER_DATASET", "shopsense_analytics_silver")
SILVER_TABLE = os.environ.get("SILVER_TABLE", "transform_data_table")

# --- Target: the Gold dataset (created by Terraform, schema defined here) -
GOLD_DATASET = os.environ.get("GOLD_DATASET", "shopsense_analytics_gold")

DIM_DATE = os.environ.get("DIM_DATE", "dim_date")
DIM_CATEGORY = os.environ.get("DIM_CATEGORY", "dim_category")
BRIDGE_CATEGORY = os.environ.get(
    "BRIDGE_CATEGORY", "bridge_category_hierarchy"
)
DIM_BRAND = os.environ.get("DIM_BRAND", "dim_brand")
DIM_PRODUCT = os.environ.get("DIM_PRODUCT", "dim_product")
DIM_SESSION = os.environ.get("DIM_SESSION", "dim_session")
FACT_EVENTS = os.environ.get("FACT_EVENTS", "fact_events")

# One row per batch: PROCESSING -> SUCCESS / FAILED, plus the run metrics.
CONTROL_TABLE = os.environ.get("CONTROL_TABLE", "ingestion_insight_control")

# --- Pub/Sub topic that triggers this function -------------------------
# Informational only (the trigger is wired by deploy.ps1).
TRIGGER_TOPIC = os.environ.get("TRIGGER_TOPIC", "shopsense-silver-loaded")


def silver_table_id() -> str:
    """`project.dataset.table` for the Silver source."""
    return f"{PROJECT_ID}.{SILVER_DATASET}.{SILVER_TABLE}"


def gold_table_id(table_name: str) -> str:
    """`project.dataset.table` for a table in the Gold dataset."""
    return f"{PROJECT_ID}.{GOLD_DATASET}.{table_name}"


def control_table_id() -> str:
    """`project.dataset.table` for the insight control table."""
    return gold_table_id(CONTROL_TABLE)
