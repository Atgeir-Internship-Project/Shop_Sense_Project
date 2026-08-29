"""
Central configuration for the staging_to_silver Cloud Function.

Same pattern as the sibling functions: plain module-level constants, no
secrets. Every value here is also referenced by deploy.ps1, so the two
must be kept in step. An environment-variable override is allowed for the
few values that might reasonably differ between a local test project and
production.
"""

import os

# --- GCP placement -------------------------------------------------------
PROJECT_ID = os.environ.get("PROJECT_ID", "shop-sense-project")
REGION = os.environ.get("REGION", "asia-south1")

# --- Source: the Bronze staging table (written by bronze_to_staging) -----
# We read only the rows for the batch named in the Pub/Sub message, never
# the whole table.
SOURCE_DATASET = os.environ.get("SOURCE_DATASET", "shopsense_analytics")
STAGING_TABLE = os.environ.get("STAGING_TABLE", "shopsense_raw_stg")

# --- Target: the Silver dataset (created by Terraform) -------------------
SILVER_DATASET = os.environ.get("SILVER_DATASET", "shopsense_analytics_silver")

# Clean, deduplicated Silver records.
SILVER_TABLE = os.environ.get("SILVER_TABLE", "transform_data_table")

# Every row we drop during cleaning is preserved here, verbatim, with the
# reason it was removed.
QUARANTINE_TABLE = os.environ.get("QUARANTINE_TABLE", "quarantine_data_table")

# One row per batch: PROCESSING -> SUCCESS / FAILED, plus the run metrics.
CONTROL_TABLE = os.environ.get(
    "CONTROL_TABLE", "ingestion_transform_control"
)

# --- Pub/Sub topics ----------------------------------------------------
# TRIGGER_TOPIC is informational only (the trigger is wired by deploy.ps1).
# SILVER_LOADED_TOPIC is the one we publish to after a successful load, so
# the downstream silver_to_gold function can pick the batch up - the same
# handoff pattern bronze_to_staging uses to reach this function.
TRIGGER_TOPIC = os.environ.get("TRIGGER_TOPIC", "shopsense-staging-loaded")
SILVER_LOADED_TOPIC = os.environ.get(
    "SILVER_LOADED_TOPIC", "shopsense-silver-loaded"
)


def staging_table_id() -> str:
    """`project.dataset.table` for the Bronze staging source."""
    return f"{PROJECT_ID}.{SOURCE_DATASET}.{STAGING_TABLE}"


def silver_table_id() -> str:
    """`project.dataset.table` for the Silver target."""
    return f"{PROJECT_ID}.{SILVER_DATASET}.{SILVER_TABLE}"


def quarantine_table_id() -> str:
    """`project.dataset.table` for the quarantine table."""
    return f"{PROJECT_ID}.{SILVER_DATASET}.{QUARANTINE_TABLE}"


def control_table_id() -> str:
    """`project.dataset.table` for the transform control table."""
    return f"{PROJECT_ID}.{SILVER_DATASET}.{CONTROL_TABLE}"
