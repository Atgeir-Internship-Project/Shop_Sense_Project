"""
End-to-end test of the Silver transformation against real BigQuery.

Skipped unless RUN_BQ_INTEGRATION=1 and Application Default Credentials
are available. It creates one temporary dataset, runs the actual
generated SQL over hand-built fixtures, asserts spec cases 1-17, and
drops the dataset afterwards.

    RUN_BQ_INTEGRATION=1 BQ_IT_PROJECT=my-project \
        pytest cloud_functions/staging_to_silver/tests/test_integration.py -v
"""

import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BQ_INTEGRATION") != "1",
    reason="set RUN_BQ_INTEGRATION=1 (needs BigQuery credentials) to run",
)

from google.cloud import bigquery  # noqa: E402  (after the skip guard)

import clients  # noqa: E402
import config  # noqa: E402
import control  # noqa: E402
from tables import ensure_silver_tables  # noqa: E402
from transform import run_transformation  # noqa: E402

_STAGING_SCHEMA = [
    bigquery.SchemaField("event_time", "STRING"),
    bigquery.SchemaField("event_type", "STRING"),
    bigquery.SchemaField("product_id", "INT64"),
    bigquery.SchemaField("category_id", "INT64"),
    bigquery.SchemaField("category_code", "STRING"),
    bigquery.SchemaField("brand", "STRING"),
    bigquery.SchemaField("price", "FLOAT64"),
    bigquery.SchemaField("user_id", "INT64"),
    bigquery.SchemaField("user_session", "STRING"),
    bigquery.SchemaField("ingestion_timestamp", "TIMESTAMP"),
    bigquery.SchemaField("source_file_name", "STRING"),
    bigquery.SchemaField("batch_id", "STRING"),
    bigquery.SchemaField("load_type", "STRING"),
]

_INGEST_TS = "2019-11-01T00:00:00+00:00"


def _row(**over):
    """A valid staging row; override any field via kwargs."""
    base = dict(
        event_time="2019-10-01 00:00:00 UTC",
        event_type="view",
        product_id=1,
        category_id=10,
        category_code="electronics.smartphone",
        brand="apple",
        price=99.99,
        user_id=100,
        user_session="sess-default",
        ingestion_timestamp=_INGEST_TS,
        source_file_name="historical/2019-Oct.csv",
        batch_id="BATCH_1",
        load_type="HISTORICAL",
    )
    base.update(over)
    return base


@pytest.fixture(scope="module")
def bq():
    client = bigquery.Client()
    project = os.environ.get("BQ_IT_PROJECT") or client.project
    dataset_id = f"{project}._silver_it_{uuid.uuid4().hex[:8]}"

    ds = bigquery.Dataset(dataset_id)
    ds.location = config.REGION
    client.create_dataset(ds)

    # Point every config table at this one throwaway dataset.
    saved = {k: getattr(config, k) for k in (
        "PROJECT_ID", "SOURCE_DATASET", "SILVER_DATASET",
        "STAGING_TABLE", "SILVER_TABLE", "QUARANTINE_TABLE", "CONTROL_TABLE",
    )}
    short = dataset_id.split(".", 1)[1]
    config.PROJECT_ID = project
    config.SOURCE_DATASET = short
    config.SILVER_DATASET = short
    config.STAGING_TABLE = "stg"
    config.SILVER_TABLE = "silver"
    config.QUARANTINE_TABLE = "quarantine"
    config.CONTROL_TABLE = "control"
    clients._bq_client = client

    client.create_table(
        bigquery.Table(f"{dataset_id}.stg", schema=_STAGING_SCHEMA)
    )
    ensure_silver_tables()

    yield client, dataset_id

    for k, v in saved.items():
        setattr(config, k, v)
    client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)


def _load_staging(client, dataset_id, rows):
    job = client.load_table_from_json(
        rows,
        f"{dataset_id}.stg",
        job_config=bigquery.LoadJobConfig(
            schema=_STAGING_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()


def _process(batch_id, source_file_name, load_type):
    control.start_processing(
        batch_id, source_file_name, load_type, datetime.now(timezone.utc)
    )
    job_id, metrics = run_transformation(batch_id, datetime.now(timezone.utc))
    metrics["bq_job_id"] = job_id
    control.finish_success(batch_id, metrics)
    return metrics


def _silver(client, dataset_id):
    return list(client.query(
        f"SELECT * FROM `{dataset_id}.silver` ORDER BY surrogate_key"
    ).result())


def _quarantine(client, dataset_id):
    return list(client.query(
        f"SELECT * FROM `{dataset_id}.quarantine`"
    ).result())


# ==========================================================================
# Batch 1: the historical load, covering cleaning + dedup cases 1-14
# ==========================================================================

@pytest.fixture(scope="module")
def batch1(bq):
    client, dataset_id = bq
    rows = [
        # cases 1/2: A, A (exact dup) and B (distinct) -> keep A once, keep B
        _row(product_id=1, user_session="dup-A"),
        _row(product_id=1, user_session="dup-A"),
        _row(product_id=2, user_session="row-B"),
        # case 3: price == 0 -> removed
        _row(product_id=3, user_session="zero", price=0.0),
        # case 4: price > 0 stays (row B already covers it)
        # case 5: user_session NULL -> removed
        _row(product_id=4, user_session=None),
        # case 6: user_session blank after trim -> removed
        _row(product_id=5, user_session="   "),
        # case 7: category_code NULL stays
        _row(product_id=6, user_session="cat-null", category_code=None),
        # case 8: brand NULL stays
        _row(product_id=7, user_session="brand-null", brand=None),
        # case 9: both NULL stays
        _row(product_id=8, user_session="both-null",
             category_code=None, brand=None),
        # case 11: unparseable event_time -> removed
        _row(product_id=9, user_session="bad-ts", event_time="not a timestamp"),
        # cases 12/13/14: trim + lowercase event_type, trim brand/category
        _row(product_id=10, user_session="  trim-me  ",
             event_type="  VIEW ", brand="  Samsung  ",
             category_code="  electronics.tv  "),
        # one more clean distinct row so source_rows == 12
        _row(product_id=11, user_session="row-D"),
    ]
    _load_staging(client, dataset_id, rows)
    metrics = _process("BATCH_1", "historical/2019-Oct.csv", "HISTORICAL")
    return metrics


def test_batch1_metrics(batch1):
    assert batch1["source_rows"] == 12
    assert batch1["price_zero_removed"] == 1
    assert batch1["session_missing_removed"] == 2
    assert batch1["invalid_timestamp_rows"] == 1
    assert batch1["exact_duplicates_removed"] == 1
    assert batch1["rows_inserted"] == 7
    assert batch1["rows_skipped"] == 0


def test_batch1_silver_has_seven_unique_rows(bq, batch1):
    client, dataset_id = bq
    rows = _silver(client, dataset_id)
    assert len(rows) == 7
    assert len({r["row_hash"] for r in rows}) == 7


def test_exact_duplicate_kept_once(bq, batch1):
    client, dataset_id = bq
    rows = _silver(client, dataset_id)
    dup_a = [r for r in rows if r["user_session"] == "dup-A"]
    assert len(dup_a) == 1


def test_distinct_rows_both_remain(bq, batch1):
    client, dataset_id = bq
    sessions = {r["user_session"] for r in _silver(client, dataset_id)}
    assert {"dup-A", "row-B", "row-D"} <= sessions


def test_price_zero_removed_and_quarantined(bq, batch1):
    client, dataset_id = bq
    q = _quarantine(client, dataset_id)
    zero = [r for r in q if r["quarantine_reason"] == "PRICE_ZERO"]
    assert len(zero) == 1 and zero[0]["price"] == 0.0


def test_positive_price_is_exact_numeric(bq, batch1):
    client, dataset_id = bq
    row_b = [r for r in _silver(client, dataset_id)
             if r["user_session"] == "row-B"][0]
    from decimal import Decimal
    assert row_b["price"] == Decimal("99.99")


def test_session_missing_rows_quarantined(bq, batch1):
    client, dataset_id = bq
    q = _quarantine(client, dataset_id)
    assert sum(r["quarantine_reason"] == "SESSION_MISSING" for r in q) == 2


def test_null_category_and_brand_are_preserved(bq, batch1):
    client, dataset_id = bq
    rows = {r["user_session"]: r for r in _silver(client, dataset_id)}
    assert rows["cat-null"]["category_code"] is None
    assert rows["brand-null"]["brand"] is None
    assert rows["both-null"]["category_code"] is None
    assert rows["both-null"]["brand"] is None


def test_event_time_parsed_to_timestamp(bq, batch1):
    client, dataset_id = bq
    row_b = [r for r in _silver(client, dataset_id)
             if r["user_session"] == "row-B"][0]
    assert row_b["event_time"] == datetime(2019, 10, 1, tzinfo=timezone.utc)


def test_invalid_timestamp_detected_and_quarantined(bq, batch1):
    client, dataset_id = bq
    q = _quarantine(client, dataset_id)
    bad = [r for r in q if r["quarantine_reason"] == "INVALID_TIMESTAMP"]
    assert len(bad) == 1 and bad[0]["event_time"] == "not a timestamp"


def test_string_cleaning_applied(bq, batch1):
    client, dataset_id = bq
    row = [r for r in _silver(client, dataset_id)
           if r["user_session"] == "trim-me"][0]
    assert row["event_type"] == "view"
    assert row["brand"] == "Samsung"
    assert row["category_code"] == "electronics.tv"


def test_duplicate_copy_is_quarantined(bq, batch1):
    client, dataset_id = bq
    q = _quarantine(client, dataset_id)
    assert sum(r["quarantine_reason"] == "EXACT_DUPLICATE" for r in q) == 1


def test_surrogate_keys_are_dense_and_start_at_one(bq, batch1):
    client, dataset_id = bq
    keys = sorted(r["surrogate_key"] for r in _silver(client, dataset_id))
    assert keys == [1, 2, 3, 4, 5, 6, 7]


# ==========================================================================
# Re-processing safety (case 16)
# ==========================================================================

def test_control_marks_batch_success(bq, batch1):
    assert control.already_succeeded("BATCH_1") is True


def test_reprocessing_same_batch_keeps_silver_stable(bq, batch1):
    client, dataset_id = bq
    before = {r["row_hash"] for r in _silver(client, dataset_id)}
    run_transformation("BATCH_1", datetime.now(timezone.utc))
    after = _silver(client, dataset_id)
    assert {r["row_hash"] for r in after} == before
    assert len(after) == 7
    assert len({r["row_hash"] for r in after}) == 7  # no duplicates created


# ==========================================================================
# Batch 2: an incremental load (cases 15 & 17)
# ==========================================================================

@pytest.fixture(scope="module")
def batch2(bq, batch1):
    client, dataset_id = bq
    rows = [
        # an exact duplicate of batch 1's "row-B" -> must be skipped
        _row(product_id=2, user_session="row-B",
             batch_id="BATCH_2", source_file_name="incremental/week1.csv",
             load_type="INCREMENTAL", ingestion_timestamp="2019-11-08T00:00:00+00:00"),
        # two genuinely new rows
        _row(product_id=20, user_session="nov-1", batch_id="BATCH_2",
             source_file_name="incremental/week1.csv", load_type="INCREMENTAL",
             ingestion_timestamp="2019-11-08T00:00:00+00:00"),
        _row(product_id=21, user_session="nov-2", batch_id="BATCH_2",
             source_file_name="incremental/week1.csv", load_type="INCREMENTAL",
             ingestion_timestamp="2019-11-08T00:00:00+00:00"),
    ]
    _load_staging(client, dataset_id, rows)
    return _process("BATCH_2", "incremental/week1.csv", "INCREMENTAL")


def test_batch2_skips_the_cross_batch_duplicate(batch2):
    assert batch2["rows_inserted"] == 2
    assert batch2["rows_skipped"] == 1


def test_batch2_surrogate_keys_continue_not_restart(bq, batch2):
    client, dataset_id = bq
    new = [r for r in _silver(client, dataset_id)
           if r["user_session"] in ("nov-1", "nov-2")]
    assert sorted(r["surrogate_key"] for r in new) == [8, 9]


def test_silver_total_after_two_batches(bq, batch2):
    client, dataset_id = bq
    rows = _silver(client, dataset_id)
    assert len(rows) == 9
    keys = sorted(r["surrogate_key"] for r in rows)
    assert keys == list(range(1, 10))  # dense 1..9, no restart
