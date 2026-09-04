"""
Cloud Function entrypoint for the fourth pipeline hop:

    Pub/Sub message from Silver  ->  build the Gold star schema

Like the upstream functions this file is only orchestration. Each real
step lives in its own module:

    message.py  - decode + vet the Pub/Sub message
    tables.py   - ensure fact_events + ingestion_insight_control exist
    control.py  - ingestion_insight_control state machine + metrics
    gold_sql.py - the BigQuery script that (re)builds the whole layer
    build.py    - submit that script and read back the metrics

The dimension / bridge tables are deterministic full rebuilds; fact_events
is an idempotent MERGE keyed on event_key. All of it happens inside
BigQuery - this function submits SQL and reads a single row of counts.
"""

from datetime import datetime, timezone

import functions_framework

import control
from build import run_gold_build
from logger import get_logger
from message import SkipMessage, parse_message
from tables import ensure_gold_tables

logger = get_logger()

# dim_category is a tiny, fixed dimension: ~126 distinct category_code
# values exploding to ~159 hierarchy nodes (+1 UNKNOWN). Flag drift.
_DIM_CATEGORY_MIN = 140
_DIM_CATEGORY_MAX = 180


@functions_framework.cloud_event
def silver_to_gold(cloud_event):
    """Runs once per 'silver loaded' message from staging_to_silver."""

    logger.info("=" * 60)
    logger.info("Silver -> Gold function started")

    batch_id = None
    job_id = None

    try:
        # --- 1. Decode the message ------------------------------------
        try:
            message = parse_message(cloud_event)
        except SkipMessage as skip:
            logger.info(str(skip))
            return

        batch_id = message["batch_id"]
        source_file_name = message["source_file_name"]
        load_type = message["load_type"]
        logger.info(
            "Batch %s | file %s | load_type %s",
            batch_id,
            source_file_name,
            load_type,
        )

        # --- 2. Ensure the appended-to tables exist ----------------
        # Runs before the control-table query below (Terraform creates the
        # Gold tables without a schema).
        ensure_gold_tables()

        # --- 3. Duplicate delivery? -------------------------------
        if control.already_succeeded(batch_id):
            logger.info("Duplicate message - Gold build already done.")
            return

        # --- 4. Claim the batch ---------------------------------
        state = control.start_processing(
            batch_id=batch_id,
            source_file_name=source_file_name,
            load_type=load_type,
            ingestion_timestamp=datetime.now(timezone.utc),
        )
        if state == "SUCCESS":
            logger.info("Batch already processed successfully.")
            return

        # --- 5. Build the Gold layer ---------------------------
        job_id, metrics = run_gold_build()
        metrics["bq_job_id"] = job_id

        # --- 6. Mark the batch done + record metrics ---------
        control.finish_success(batch_id, metrics)

        _log_summary(batch_id, source_file_name, load_type, job_id, metrics)
        logger.info("=" * 60)

    except Exception as error:
        logger.error("Silver -> Gold failed: %s", error)

        # Best-effort: flip the batch to FAILED so a retry picks it up.
        # The dimension rebuilds and the fact MERGE are each safe to
        # re-run, so a later attempt recovers cleanly.
        if batch_id:
            try:
                control.finish_failed(batch_id, job_id)
            except Exception as control_error:  # noqa: BLE001
                logger.error(
                    "Could not mark batch %s FAILED: %s",
                    batch_id,
                    control_error,
                )

        raise


def _log_summary(batch_id, source_file_name, load_type, job_id, metrics):
    """One structured summary line, plus a WARNING for any check that failed."""

    logger.info(
        "Silver -> Gold done. batch=%s file=%s load_type=%s "
        "silver_rows=%s dim_date=%s dim_category=%s bridge=%s dim_brand=%s "
        "dim_product=%s dim_session=%s fact_inserted=%s fact_total=%s "
        "fk_failures=%s duplicate_event_keys=%s bq_job_id=%s status=SUCCESS",
        batch_id,
        source_file_name,
        load_type,
        metrics["silver_rows"],
        metrics["dim_date_rows"],
        metrics["dim_category_rows"],
        metrics["bridge_category_hierarchy_rows"],
        metrics["dim_brand_rows"],
        metrics["dim_product_rows"],
        metrics["dim_session_rows"],
        metrics["fact_events_inserted"],
        metrics["fact_events_total"],
        metrics["fk_resolution_failures"],
        metrics["duplicate_event_keys"],
        job_id,
    )

    if metrics["fk_resolution_failures"]:
        logger.warning(
            "%s fact_events rows have an unresolved foreign key.",
            metrics["fk_resolution_failures"],
        )
    if metrics["duplicate_event_keys"]:
        logger.warning(
            "%s duplicate event_key value(s) in fact_events - MERGE key "
            "may be wrong.",
            metrics["duplicate_event_keys"],
        )
    if metrics["fact_events_total"] != metrics["silver_rows"]:
        logger.warning(
            "fact_events_total (%s) != silver_rows (%s) - expected equal "
            "once every batch is processed.",
            metrics["fact_events_total"],
            metrics["silver_rows"],
        )
    if not (_DIM_CATEGORY_MIN <= metrics["dim_category_rows"] <= _DIM_CATEGORY_MAX):
        logger.warning(
            "dim_category has %s rows, outside the expected ~159.",
            metrics["dim_category_rows"],
        )
