"""
Make sure the two Gold tables that are *appended to* (rather than rebuilt
every run) exist with their schema:

    fact_events                  - the MERGE target, partitioned + clustered
    ingestion_insight_control    - the DML state machine

Terraform creates these tables without column definitions (same as Bronze
and Silver), and CREATE TABLE IF NOT EXISTS will NOT retrofit a schema
onto a table that already exists - it just no-ops. So this uses the
BigQuery client to actually set the schema, exactly like Silver's
_ensure_table does.

fact_events additionally needs partitioning, which cannot be added to an
existing table. If the placeholder has no partitioning it is dropped and
recreated (safe - a schemaless placeholder has never been written to).

The six dimension / bridge tables are NOT handled here - the build script
recreates them with CREATE OR REPLACE TABLE (<columns>) AS SELECT, which
pins their schema at the same time and works fine on a placeholder.
"""

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from clients import get_bigquery_client
from config import FACT_EVENTS, control_table_id, gold_table_id
from logger import get_logger
from schemas import (
    CONTROL_SCHEMA,
    FACT_EVENTS_CLUSTER_FIELDS,
    FACT_EVENTS_PARTITION_FIELD,
    FACT_EVENTS_SCHEMA,
)

logger = get_logger()


def _set_schema_if_missing(table_id: str, schema: list) -> None:
    """Add `schema` to the table if it currently has none. Never drops."""

    client = get_bigquery_client()
    try:
        table = client.get_table(table_id)
    except NotFound:
        logger.info("Creating %s", table_id)
        client.create_table(bigquery.Table(table_id, schema=schema))
        return

    if table.schema:
        logger.info("Schema already present: %s", table_id)
        return

    logger.info("Retrofitting schema onto empty table: %s", table_id)
    table.schema = schema
    client.update_table(table, ["schema"])


def _ensure_fact_events() -> None:
    """
    fact_events must be partitioned by date_key and clustered. Create it
    if missing; retrofit the schema if it exists un-partitioned but with
    partitioning already configured; otherwise (schemaless *and*
    un-partitioned placeholder) drop and recreate it properly.
    """

    client = get_bigquery_client()
    fact_id = gold_table_id(FACT_EVENTS)

    def _fresh() -> bigquery.Table:
        t = bigquery.Table(fact_id, schema=FACT_EVENTS_SCHEMA)
        t.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=FACT_EVENTS_PARTITION_FIELD,
        )
        t.clustering_fields = FACT_EVENTS_CLUSTER_FIELDS
        return t

    try:
        table = client.get_table(fact_id)
    except NotFound:
        logger.info("Creating partitioned fact_events: %s", fact_id)
        client.create_table(_fresh())
        return

    if table.schema:
        logger.info("fact_events already has a schema: %s", fact_id)
        return

    if table.time_partitioning and table.time_partitioning.field == \
            FACT_EVENTS_PARTITION_FIELD:
        logger.info("Retrofitting schema onto partitioned fact_events.")
        table.schema = FACT_EVENTS_SCHEMA
        if not table.clustering_fields:
            table.clustering_fields = FACT_EVENTS_CLUSTER_FIELDS
        client.update_table(table, ["schema", "clustering_fields"])
        return

    logger.info(
        "fact_events placeholder is un-partitioned - recreating it "
        "partitioned + clustered (no data to lose)."
    )
    try:
        client.delete_table(fact_id)
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            f"Cannot recreate {fact_id} as a partitioned table: {error}. "
            f"If it has deletion protection, drop it once by hand "
            f"(`bq rm -f -t {fact_id}`) or set deletion_protection=false "
            f"in Terraform, then re-run."
        ) from error
    client.create_table(_fresh())


def ensure_gold_tables() -> None:
    """Guarantee fact_events and ingestion_insight_control are usable."""

    _ensure_fact_events()
    _set_schema_if_missing(control_table_id(), CONTROL_SCHEMA)
    logger.info("Gold fact + control tables are in place.")
