"""
Make sure the three Silver-dataset tables exist before we use them.

Terraform is meant to own these, but we don't want a deploy-ordering
problem to break ingestion. This module can create a missing table from
the schema in schemas.py, or append columns that a pre-existing table is
missing. It never drops a table and never drops or retypes a column.

Note on modes: when we create a table ourselves we honour the REQUIRED
flags in the schema. When we *alter* an existing table we can only add
columns as NULLABLE - BigQuery rejects adding a REQUIRED column to a
table that already has rows - so the alter path forces NULLABLE.
"""

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from clients import get_bigquery_client
from config import control_table_id, quarantine_table_id, silver_table_id
from logger import get_logger
from schemas import CONTROL_SCHEMA, QUARANTINE_SCHEMA, SILVER_SCHEMA

logger = get_logger()


def _ensure_table(table_id: str, schema: list) -> None:
    """Create `table_id` from `schema`, or add any columns it is missing."""

    client = get_bigquery_client()

    try:
        table = client.get_table(table_id)
    except NotFound:
        logger.info("Table not found, creating: %s", table_id)
        client.create_table(bigquery.Table(table_id, schema=schema))
        logger.info("Created table: %s", table_id)
        return

    existing = {field.name for field in table.schema}
    missing = [field for field in schema if field.name not in existing]

    if not missing:
        logger.info("Table schema already compatible: %s", table_id)
        return

    # Re-declare the additions as NULLABLE - see the module docstring.
    additions = [
        bigquery.SchemaField(f.name, f.field_type, mode="NULLABLE")
        for f in missing
    ]
    logger.info(
        "Adding missing columns to %s: %s",
        table_id,
        ", ".join(f.name for f in additions),
    )
    table.schema = list(table.schema) + additions
    client.update_table(table, ["schema"])
    logger.info("Columns added to %s.", table_id)


def ensure_silver_tables() -> None:
    """Guarantee the Silver, quarantine and control tables are all usable."""

    _ensure_table(silver_table_id(), SILVER_SCHEMA)
    _ensure_table(quarantine_table_id(), QUARANTINE_SCHEMA)
    _ensure_table(control_table_id(), CONTROL_SCHEMA)
