"""
End-to-end test of the Gold build against real BigQuery.

Skipped unless RUN_BQ_INTEGRATION=1 with Application Default Credentials.
Creates one temporary dataset holding a fake Silver table plus the Gold
tables, runs the real generated build script over hand-built fixtures,
and asserts the star schema, the integrity checks and idempotency.

    RUN_BQ_INTEGRATION=1 BQ_IT_PROJECT=my-project \
        pytest cloud_functions/silver_to_gold/tests/test_integration.py -v
"""

import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BQ_INTEGRATION") != "1",
    reason="set RUN_BQ_INTEGRATION=1 (needs BigQuery credentials) to run",
)

from google.cloud import bigquery  # noqa: E402

import build  # noqa: E402
import clients  # noqa: E402
import config  # noqa: E402
import control  # noqa: E402
from tables import ensure_gold_tables  # noqa: E402

_SILVER_SCHEMA = [
    bigquery.SchemaField("surrogate_key", "INT64"),
    bigquery.SchemaField("row_hash", "STRING"),
    bigquery.SchemaField("event_time", "TIMESTAMP"),
    bigquery.SchemaField("event_type", "STRING"),
    bigquery.SchemaField("product_id", "INT64"),
    bigquery.SchemaField("category_id", "INT64"),
    bigquery.SchemaField("category_code", "STRING"),
    bigquery.SchemaField("brand", "STRING"),
    bigquery.SchemaField("price", "NUMERIC"),
    bigquery.SchemaField("user_id", "INT64"),
    bigquery.SchemaField("user_session", "STRING"),
    bigquery.SchemaField("batch_id", "STRING"),
    bigquery.SchemaField("silver_loaded_at", "TIMESTAMP"),
]

_SK = [0]


def _row(**over):
    _SK[0] += 1
    base = dict(
        surrogate_key=_SK[0],
        row_hash=f"h{_SK[0]}",
        event_time="2019-10-01T00:00:00Z",
        event_type="view",
        product_id=1,
        category_id=10,
        category_code="electronics.smartphone",
        brand="apple",
        price="99.99",
        user_id=100,
        user_session="s-default",
        batch_id="BATCH_1",
        silver_loaded_at="2019-11-01T00:00:00Z",
    )
    base.update(over)
    return base


@pytest.fixture(scope="module")
def gold(bq_dataset):
    client, dataset_id, short = bq_dataset

    client.create_table(
        bigquery.Table(f"{dataset_id}.transform_data_table", schema=_SILVER_SCHEMA)
    )

    rows = [
        # electronics.smartphone : 3 views, 1 cart, 1 purchase
        _row(product_id=1, user_session="s1", event_type="view"),
        _row(product_id=1, user_session="s1", event_type="view"),
        _row(product_id=1, user_session="s1", event_type="cart"),
        _row(product_id=1, user_session="s2", event_type="view"),
        _row(product_id=1, user_session="s2", event_type="purchase"),
        # appliances.kitchen.oven : 4-part-safe 3-level hierarchy
        _row(product_id=2, user_session="s3", category_code="appliances.kitchen.oven",
             brand="bosch", event_type="view"),
        _row(product_id=2, user_session="s3", category_code="appliances.kitchen.oven",
             brand=None, event_type="cart"),           # brand fill-in case
        # apparel.shoes with two different category_id values, same code
        _row(product_id=3, user_session="s4", category_code="apparel.shoes",
             category_id=50, brand="nike", event_type="view"),
        _row(product_id=3, user_session="s4", category_code="apparel.shoes",
             category_id=51, brand="nike", event_type="purchase"),
        # NULL category_code and NULL brand -> UNKNOWN members
        _row(product_id=4, user_session="s5", category_code=None, brand=None,
             event_type="view"),
        # multi-user session
        _row(product_id=1, user_session="s6", user_id=200, event_type="view"),
        _row(product_id=1, user_session="s6", user_id=201, event_type="view"),
    ]
    job = client.load_table_from_json(
        rows,
        f"{dataset_id}.transform_data_table",
        job_config=bigquery.LoadJobConfig(schema=_SILVER_SCHEMA),
    )
    job.result()

    ensure_gold_tables()
    job_id, metrics = _run()
    return client, dataset_id, metrics


@pytest.fixture(scope="module")
def bq_dataset():
    client = bigquery.Client()
    project = os.environ.get("BQ_IT_PROJECT") or client.project
    dataset_id = f"{project}._gold_it_{uuid.uuid4().hex[:8]}"
    short = dataset_id.split(".", 1)[1]

    ds = bigquery.Dataset(dataset_id)
    ds.location = config.REGION
    client.create_dataset(ds)

    saved = {k: getattr(config, k) for k in
             ("PROJECT_ID", "SILVER_DATASET", "SILVER_TABLE", "GOLD_DATASET")}
    config.PROJECT_ID = project
    config.SILVER_DATASET = short
    config.SILVER_TABLE = "transform_data_table"
    config.GOLD_DATASET = short
    clients._bq_client = client

    yield client, dataset_id, short

    for k, v in saved.items():
        setattr(config, k, v)
    client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)


def _run():
    control.start_processing("BATCH_1", "f.csv", "HISTORICAL",
                             datetime.now(timezone.utc))
    job_id, metrics = build.run_gold_build()
    metrics["bq_job_id"] = job_id
    control.finish_success("BATCH_1", metrics)
    return job_id, metrics


def _q(client, dataset_id, sql):
    return list(client.query(sql.format(d=dataset_id)).result())


# ==========================================================================

def test_fact_row_count_matches_silver(gold):
    _, _, m = gold
    assert m["fact_events_inserted"] == 12
    assert m["fact_events_total"] == 12
    assert m["silver_rows"] == 12


def test_no_fk_failures_and_no_duplicate_event_keys(gold):
    _, _, m = gold
    assert m["fk_resolution_failures"] == 0
    assert m["duplicate_event_keys"] == 0


def test_dim_category_nodes_and_hierarchy(gold):
    client, dataset_id, _ = gold
    rows = _q(client, dataset_id, "SELECT category_code, level_number, is_leaf, "
              "parent_category_key FROM `{d}.dim_category` ORDER BY category_code")
    codes = {r["category_code"] for r in rows}
    # 3 codes -> nodes: electronics, electronics.smartphone, appliances,
    # appliances.kitchen, appliances.kitchen.oven, apparel, apparel.shoes + UNKNOWN
    assert codes == {
        "electronics", "electronics.smartphone",
        "appliances", "appliances.kitchen", "appliances.kitchen.oven",
        "apparel", "apparel.shoes", "UNKNOWN",
    }
    by_code = {r["category_code"]: r for r in rows}
    assert by_code["appliances.kitchen.oven"]["level_number"] == 3
    assert by_code["appliances.kitchen.oven"]["is_leaf"] is True
    assert by_code["appliances"]["is_leaf"] is False
    assert by_code["appliances"]["parent_category_key"] is None


def test_bridge_rolls_appliances_down_to_oven(gold):
    client, dataset_id, _ = gold
    rows = _q(client, dataset_id, """
        SELECT b.hierarchy_level
        FROM `{d}.bridge_category_hierarchy` b
        JOIN `{d}.dim_category` a ON a.category_key = b.ancestor_category_key
        JOIN `{d}.dim_category` d ON d.category_key = b.descendant_category_key
        WHERE a.category_code = 'appliances'
          AND d.category_code = 'appliances.kitchen.oven'
    """)
    assert [r["hierarchy_level"] for r in rows] == [2]


def test_dim_product_prefers_non_null_brand(gold):
    client, dataset_id, _ = gold
    rows = _q(client, dataset_id, """
        SELECT b.brand
        FROM `{d}.dim_product` p
        JOIN `{d}.dim_brand` b ON b.brand_key = p.brand_key
        WHERE p.product_id = 2
    """)
    assert rows[0]["brand"] == "bosch"  # not the NULL from the cart row


def test_dim_category_keyed_by_code_not_category_id(gold):
    client, dataset_id, _ = gold
    # apparel.shoes had two category_id values but must be ONE dim_category row
    rows = _q(client, dataset_id,
              "SELECT COUNT(*) c FROM `{d}.dim_category` "
              "WHERE category_code = 'apparel.shoes'")
    assert rows[0]["c"] == 1


def test_dim_session_rollups(gold):
    client, dataset_id, _ = gold
    rows = _q(client, dataset_id, """
        SELECT user_session, event_count, has_purchase, is_multi_user
        FROM `{d}.dim_session` ORDER BY user_session
    """)
    by = {r["user_session"]: r for r in rows}
    assert by["s2"]["has_purchase"] is True
    assert by["s1"]["has_purchase"] is False
    assert by["s6"]["is_multi_user"] is True
    assert by["s1"]["is_multi_user"] is False


def test_unknown_members_present(gold):
    client, dataset_id, _ = gold
    cat = _q(client, dataset_id,
             "SELECT COUNT(*) c FROM `{d}.dim_category` WHERE category_key = -1")
    brand = _q(client, dataset_id,
               "SELECT COUNT(*) c FROM `{d}.dim_brand` WHERE brand_key = -1")
    assert cat[0]["c"] == 1 and brand[0]["c"] == 1


def test_rerun_is_idempotent(gold):
    client, dataset_id, _ = gold
    before = _q(client, dataset_id, "SELECT COUNT(*) c FROM `{d}.fact_events`")[0]["c"]
    job_id, metrics = build.run_gold_build()
    after = _q(client, dataset_id, "SELECT COUNT(*) c FROM `{d}.fact_events`")[0]["c"]
    assert metrics["fact_events_inserted"] == 0
    assert after == before == 12
