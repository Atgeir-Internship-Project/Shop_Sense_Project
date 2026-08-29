"""
Unit tests that need no BigQuery connection: message decoding, the
control-table metric contract, and the structure of the generated Gold
build script (dimension rebuilds, the idempotent fact MERGE, the star
keys, the integrity-check metrics).
"""

import base64
import json
import types

import pytest

import config
import gold_sql
import message
import schemas
import tables


# --------------------------------------------------------------------------
# message decoding
# --------------------------------------------------------------------------

def _event(payload: dict):
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8"))
    return types.SimpleNamespace(data={"message": {"data": encoded}})


def test_parse_message_returns_batch_fields():
    out = message.parse_message(_event({
        "batch_id": "BATCH_9",
        "source_file_name": "historical/2019-Oct.csv",
        "load_type": "HISTORICAL",
    }))
    assert out == {
        "batch_id": "BATCH_9",
        "source_file_name": "historical/2019-Oct.csv",
        "load_type": "HISTORICAL",
    }


@pytest.mark.parametrize("missing", ["batch_id", "source_file_name", "load_type"])
def test_parse_message_rejects_missing_field(missing):
    payload = {"batch_id": "B", "source_file_name": "f", "load_type": "HISTORICAL"}
    del payload[missing]
    with pytest.raises(message.SkipMessage):
        message.parse_message(_event(payload))


def test_parse_message_rejects_unreadable_envelope():
    bad = types.SimpleNamespace(data={"message": {"data": "!!!"}})
    with pytest.raises(message.SkipMessage):
        message.parse_message(bad)


# --------------------------------------------------------------------------
# control-table contract
# --------------------------------------------------------------------------

def test_every_metric_column_is_declared_in_the_control_schema():
    control_names = {f.name for f in schemas.CONTROL_SCHEMA}
    for col in schemas.METRIC_COLUMNS:
        assert col in control_names


# --------------------------------------------------------------------------
# ensure_gold_tables - schema is set via the BigQuery client
# --------------------------------------------------------------------------

def test_fact_events_schema_carries_partition_and_cluster_fields():
    assert schemas.FACT_EVENTS_PARTITION_FIELD == "date_key"
    assert schemas.FACT_EVENTS_CLUSTER_FIELDS == [
        "category_key", "product_key", "session_key"
    ]
    names = [f.name for f in schemas.FACT_EVENTS_SCHEMA]
    assert names[0] == "event_key" and "gold_loaded_at" in names


def test_ensure_creates_missing_tables_partitioned():
    from unittest.mock import MagicMock
    from google.api_core.exceptions import NotFound
    import clients

    fake = MagicMock()
    fake.get_table.side_effect = NotFound("nope")
    clients._bq_client = fake
    try:
        tables.ensure_gold_tables()
    finally:
        clients._bq_client = None

    created = [c.args[0] for c in fake.create_table.call_args_list]
    assert any(t.table_id == "fact_events" for t in created)
    assert any(t.table_id == "ingestion_insight_control" for t in created)
    fact = next(t for t in created if t.table_id == "fact_events")
    assert fact.time_partitioning.field == "date_key"
    assert fact.clustering_fields == ["category_key", "product_key", "session_key"]
    fake.delete_table.assert_not_called()  # nothing dropped when tables are absent


# --------------------------------------------------------------------------
# generated Gold build script
# --------------------------------------------------------------------------

@pytest.fixture
def sql(monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ID", "test-proj")
    monkeypatch.setattr(config, "SILVER_DATASET", "sil_ds")
    monkeypatch.setattr(config, "SILVER_TABLE", "silver")
    monkeypatch.setattr(config, "GOLD_DATASET", "gold_ds")
    return gold_sql.build_gold_sql()


def test_dimensions_are_full_rebuilds(sql):
    for dim in ("dim_date", "dim_category", "bridge_category_hierarchy",
                "dim_brand", "dim_product", "dim_session"):
        assert f"CREATE OR REPLACE TABLE `test-proj.gold_ds.{dim}`" in sql
    # exactly the six dimension/bridge tables, nothing else
    assert sql.count("CREATE OR REPLACE TABLE") == 6


def test_fact_events_is_a_merge_not_a_replace(sql):
    assert "MERGE `test-proj.gold_ds.fact_events` T" in sql
    assert "CREATE OR REPLACE TABLE `test-proj.gold_ds.fact_events`" not in sql
    assert "ON T.event_key = S.event_key" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql


def test_event_key_is_reused_from_silver_surrogate_key(sql):
    assert "CAST(s.surrogate_key AS STRING) AS event_key" in sql


def test_star_keys_are_deterministic_hashes(sql):
    assert "FARM_FINGERPRINT(category_code) AS category_key" in sql
    assert "FARM_FINGERPRINT(brand) AS brand_key" in sql
    assert "FARM_FINGERPRINT(CAST(c.product_id AS STRING)) AS product_key" in sql
    assert "FARM_FINGERPRINT(user_session) AS session_key" in sql


def test_unknown_members_use_minus_one(sql):
    # dim_category and dim_brand each contribute one UNKNOWN row
    assert "SELECT -1, 'UNKNOWN', 'UNKNOWN', NULL, 0, TRUE" in sql
    assert "SELECT -1, 'UNKNOWN';" in sql
    # fact maps NULL category/brand to the -1 member
    assert "COALESCE(dc.category_key, -1) AS category_key" in sql
    assert "COALESCE(db.brand_key, -1) AS brand_key" in sql


def test_category_hierarchy_uses_recursion_over_dim_category(sql):
    assert "WITH RECURSIVE closure AS" in sql
    assert "d.parent_category_key = c.descendant_category_key" in sql


def test_category_id_is_passthrough_only_never_a_key(sql):
    # category_id appears in the fact SELECT as a plain column ...
    assert "s.category_id," in sql
    # ... and never as the basis of a key
    assert "FARM_FINGERPRINT(CAST(s.category_id" not in sql
    assert "category_id) AS category_key" not in sql


def test_only_the_three_real_event_types_are_loaded(sql):
    assert "s.event_type IN ('view', 'cart', 'purchase')" in sql
    assert "remove_from_cart" not in sql


def test_fact_flags_and_grain_counter(sql):
    assert "IF(s.event_type = 'view', 1, 0) AS is_view" in sql
    assert "IF(s.event_type = 'cart', 1, 0) AS is_cart" in sql
    assert "IF(s.event_type = 'purchase', 1, 0) AS is_purchase" in sql
    assert "1 AS event_count" in sql


def test_metrics_select_reports_the_integrity_checks(sql):
    for col in ("silver_rows", "dim_category_rows", "dim_product_rows",
                "fact_events_inserted", "fact_events_total",
                "fk_resolution_failures", "duplicate_event_keys"):
        assert col in sql
    assert "COUNT(*) - COUNT(DISTINCT event_key)" in sql
