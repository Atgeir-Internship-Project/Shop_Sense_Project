"""
Table naming + making sure the staging table exists.

Terraform owns the "real" table definitions, but we don't want a deploy
ordering problem to break ingestion, so this module can create or repair
the staging table on the fly. It never drops anything - at worst it adds
missing columns.
"""

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from clients import get_bigquery_client
from config import BIGQUERY_DATASET, STAGING_TABLE
from logger import get_logger
from schemas import STAGING_SCHEMA

logger = get_logger()

# The project id is fixed for this pipeline. Kept here (not in config.py)
# so the naming logic stays self-contained in one place.
_PROJECT_ID = "shop-sense-project"


def get_table_id(table_name: str) -> str:
    """
    Build a fully-qualified `project.dataset.table` id.

    BigQuery DML (INSERT / UPDATE) needs the fully-qualified form, so we
    always go through this helper rather than hand-formatting names.
    """

    return f"{_PROJECT_ID}.{BIGQUERY_DATASET}.{table_name}"


def ensure_staging_table() -> None:
    """
    Guarantee that the staging table exists with every column we need.

    Three possible situations:
      1. Table missing entirely  -> create it from STAGING_SCHEMA.
      2. Table exists, all columns present -> do nothing.
      3. Table exists but is missing some columns (e.g. we added metadata
         later) -> ALTER it to append the missing ones. Existing data is
         untouched; the new columns are just NULL for old rows.
    """

    bq_client = get_bigquery_client()
    table_id = get_table_id(STAGING_TABLE)

    try:
        table = bq_client.get_table(table_id)
    except NotFound:
        # Situation 1: nothing there yet, create it and we're done.
        logger.info("Staging table not found, creating: %s", table_id)
        bq_client.create_table(
            bigquery.Table(table_id, schema=STAGING_SCHEMA)
        )
        logger.info("Created staging table: %s", table_id)
        return

    # Table exists - compare what's there against what we expect.
    existing_columns = {field.name for field in table.schema}
    missing = [
        field
        for field in STAGING_SCHEMA
        if field.name not in existing_columns
    ]

    if not missing:
        # Situation 2: nothing to do.
        logger.info("Staging table schema is already compatible.")
        return

    # Situation 3: append the missing columns.
    logger.info(
        "Adding missing staging columns: %s",
        ", ".join(f.name for f in missing),
    )
    table.schema = list(table.schema) + missing
    bq_client.update_table(table, ["schema"])
    logger.info("Missing staging columns added successfully.")
