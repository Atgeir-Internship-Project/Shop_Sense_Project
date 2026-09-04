"""
Unit tests that need no BigQuery connection.

They cover the pure logic: message decoding, the row-identity contract,
the control-table metric columns, and the structure of the generated
transformation SQL. The data-semantics cases (1-17 in the spec) are
exercised end-to-end in test_integration.py, which needs credentials.
"""

import base64
import json
import types

import pytest

import config
import control
import message
import schemas
import silver_sql


# --------------------------------------------------------------------------
# row identity contract
# --------------------------------------------------------------------------

def test_row_hash_columns_are_the_nine_business_columns():
    assert schemas.ROW_HASH_COLUMNS == [
        "event_time", "event_type", "product_id", "category_id",
        "category_code", "brand", "price", "user_id", "user_session",
    ]


def test_surrogate_key_is_not_part_of_the_hash():
    assert "surrogate_key" not in schemas.ROW_HASH_COLUMNS


# --------------------------------------------------------------------------
# control table
# --------------------------------------------------------------------------

def test_every_metric_column_exists_in_the_control_schema():
    schema_names = {f.name for f in schemas.CONTROL_SCHEMA}
    for col in control.METRIC_COLUMNS:
        assert col in schema_names


# --------------------------------------------------------------------------
# message decoding
# --------------------------------------------------------------------------

def _event(payload: dict):
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8"))
    return types.SimpleNamespace(data={"message": {"data": encoded}})


def test_parse_message_returns_batch_fields():
    out = message.parse_message(_event({
        "batch_id": "BATCH_123",
        "source_file_name": "incremental/week1.csv",
        "load_type": "INCREMENTAL",
        "row_count": 10,
    }))
    assert out == {
        "batch_id": "BATCH_123",
        "source_file_name": "incremental/week1.csv",
        "load_type": "INCREMENTAL",
        "row_count": 10,
    }


@pytest.mark.parametrize("missing", ["batch_id", "source_file_name", "load_type"])
def test_parse_message_rejects_missing_required_field(missing):
    payload = {
        "batch_id": "BATCH_123",
        "source_file_name": "f.csv",
        "load_type": "INCREMENTAL",
    }
    del payload[missing]
    with pytest.raises(message.SkipMessage):
        message.parse_message(_event(payload))


def test_parse_message_rejects_unreadable_envelope():
    bad = types.SimpleNamespace(data={"message": {"data": "!!!not-base64!!!"}})
    with pytest.raises(message.SkipMessage):
        message.parse_message(bad)


# --------------------------------------------------------------------------
# generated SQL
# --------------------------------------------------------------------------

@pytest.fixture
def sql(monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ID", "test-proj")
    monkeypatch.setattr(config, "SOURCE_DATASET", "src_ds")
    monkeypatch.setattr(config, "STAGING_TABLE", "stg")
    monkeypatch.setattr(config, "SILVER_DATASET", "sil_ds")
    monkeypatch.setattr(config, "SILVER_TABLE", "silver")
    monkeypatch.setattr(config, "QUARANTINE_TABLE", "quar")
    return silver_sql.build_transform_sql()


def test_sql_targets_the_configured_tables(sql):
    assert "`test-proj.src_ds.stg`" in sql
    assert "`test-proj.sil_ds.silver`" in sql
    assert "`test-proj.sil_ds.quar`" in sql


def test_sql_is_transactional_and_idempotent(sql):
    assert "BEGIN TRANSACTION" in sql
    assert "COMMIT TRANSACTION" in sql
    assert "MERGE `test-proj.sil_ds.silver` T" in sql
    # only inserts rows Silver does not already have
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "NOT EXISTS" in sql


def test_sql_reads_only_the_one_batch(sql):
    assert "WHERE batch_id = @batch_id" in sql


def test_sql_applies_the_cleaning_rules(sql):
    assert "SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S %Z', TRIM(src_event_time))" in sql
    assert "LOWER(TRIM(src_event_type))" in sql
    assert "NULLIF(TRIM(src_category_code), '')" in sql
    assert "NULLIF(TRIM(src_brand), '')" in sql
    assert "NULLIF(TRIM(src_user_session), '')" in sql
    assert "CAST(src_price AS NUMERIC)" in sql


def test_sql_tags_every_removal_reason(sql):
    for reason in ("SESSION_MISSING", "PRICE_ZERO", "INVALID_TIMESTAMP",
                   "EXACT_DUPLICATE"):
        assert f"'{reason}'" in sql


def test_sql_hashes_the_cleaned_record_with_sha256(sql):
    assert "TO_HEX(SHA256(TO_JSON_STRING(STRUCT(" in sql


def test_sql_hash_struct_uses_the_fixed_column_order(sql):
    start = sql.index("TO_JSON_STRING(STRUCT(")
    struct_block = sql[start:sql.index("))) AS row_hash", start)]
    positions = [struct_block.index(f" AS {name}") for name in schemas.ROW_HASH_COLUMNS]
    assert positions == sorted(positions)


def test_sql_continues_surrogate_key_from_current_max(sql):
    assert "IFNULL(MAX(surrogate_key), 0)" in sql
    assert "+ ROW_NUMBER() OVER (ORDER BY s.row_hash) AS surrogate_key" in sql


def test_sql_returns_one_metrics_row(sql):
    for col in ("source_rows", "price_zero_removed", "session_missing_removed",
                "invalid_timestamp_rows", "exact_duplicates_removed",
                "merge_candidates", "rows_inserted"):
        assert col in sql
