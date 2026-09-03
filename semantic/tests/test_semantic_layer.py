"""
Unit tests for the ShopSense semantic layer.

These test the SQL *builder* - that it only emits catalog-defined names, binds
every value as a parameter, and shapes the query correctly. They do not touch
BigQuery.
"""

import pytest

from semantic import SemanticLayer, SemanticLayerError


@pytest.fixture(scope="module")
def sl() -> SemanticLayer:
    return SemanticLayer.load()


# -- catalog loads & validates ------------------------------------------

def test_catalog_loads_with_core_metrics_and_dimensions(sl):
    assert "conversion_rate" in sl.metrics
    assert "revenue" in sl.metrics
    assert "category" in sl.dimensions
    assert "category_l1" in sl.dimensions
    assert {"day", "week", "month"}.issubset(sl.time_grains)
    assert "high_intent_never_purchase" in sl.segments


def test_describe_is_json_shaped(sl):
    described = sl.describe()
    assert described["base_view"].endswith("vw_semantic_events")
    assert described["metrics"]["revenue"]["type"] == "additive"
    assert "week" in described["time_grains"]


# -- name resolution ---------------------------------------------------

def test_synonyms_resolve(sl):
    assert sl.resolve_dimension("department") == "category_l1"
    assert sl.resolve_dimension("Product Category") == "category"
    assert sl.resolve_metric("Conversion Rate") == "conversion_rate"


def test_unknown_names_raise(sl):
    with pytest.raises(SemanticLayerError):
        sl.resolve_metric("gross_margin")
    with pytest.raises(SemanticLayerError):
        sl.resolve_dimension("warehouse")


def test_unknown_metric_in_build_raises(sl):
    with pytest.raises(SemanticLayerError):
        sl.build_aggregate_query(metrics=["not_a_metric"])


# -- basic query shapes ----------------------------------------------

def test_metric_only_query_has_no_group_by(sl):
    q = sl.build_aggregate_query(metrics=["revenue", "purchases"])
    assert "GROUP BY" not in q.sql
    assert "SUM(IF(is_purchase = 1, price, 0)) AS revenue" in q.sql
    assert q.sql.rstrip().endswith("LIMIT 1000")  # default_row_limit
    assert q.parameters == []


def test_metric_by_dimension_groups_and_orders(sl):
    q = sl.build_aggregate_query(
        metrics=["revenue"], dimensions=["category"], limit=10
    )
    assert "category_name AS category" in q.sql
    assert "GROUP BY 1" in q.sql
    assert "ORDER BY revenue DESC" in q.sql
    assert q.sql.rstrip().endswith("LIMIT 10")


def test_time_grain_becomes_first_group_column(sl):
    q = sl.build_aggregate_query(
        metrics=["revenue", "conversion_rate"], time_grain="week"
    )
    assert "DATE_TRUNC(event_date, WEEK(MONDAY)) AS week" in q.sql
    assert "GROUP BY 1" in q.sql


def test_limit_is_clamped_to_max(sl):
    q = sl.build_aggregate_query(metrics=["events"], dimensions=["brand"], limit=10**9)
    assert q.sql.rstrip().endswith("LIMIT 10000")


# -- filters are always parameterised (injection safety) ----------------

def test_eq_filter_is_parameterised(sl):
    q = sl.build_aggregate_query(
        metrics=["revenue"],
        dimensions=["category"],
        filters=[{"field": "category_l1", "op": "eq", "value": "electronics"}],
    )
    assert "category_l1 = @p0" in q.sql
    assert "electronics" not in q.sql            # value never inlined
    assert q.parameters == [{"name": "p0", "type": "STRING", "value": "electronics"}]


def test_in_filter_uses_array_param(sl):
    q = sl.build_aggregate_query(
        metrics=["conversion_rate"],
        dimensions=["category_l1"],
        filters=[{"field": "category_l1", "op": "in",
                  "value": ["electronics", "apparel"]}],
    )
    assert "category_l1 IN UNNEST(@p0)" in q.sql
    assert q.parameters[0]["type"] == "ARRAY<STRING>"
    assert q.parameters[0]["value"] == ["electronics", "apparel"]


def test_last_n_days_anchors_on_data_not_clock(sl):
    q = sl.build_aggregate_query(
        metrics=["view_to_cart_rate"],
        dimensions=["category"],
        filters=[{"field": "event_date", "op": "last_n_days", "value": 7}],
    )
    assert "DATE_SUB((SELECT MAX(event_date)" in q.sql
    assert "INTERVAL @p0 DAY" in q.sql
    assert "CURRENT_DATE" not in q.sql
    assert q.parameters == [{"name": "p0", "type": "INT64", "value": 7}]


def test_last_n_days_rejected_on_non_date_dimension(sl):
    with pytest.raises(SemanticLayerError):
        sl.build_aggregate_query(
            metrics=["revenue"],
            filters=[{"field": "brand", "op": "last_n_days", "value": 7}],
        )


def test_malicious_filter_value_cannot_break_out(sl):
    evil = "x'); DROP TABLE fact_events; --"
    q = sl.build_aggregate_query(
        metrics=["revenue"],
        filters=[{"field": "brand", "op": "eq", "value": evil}],
    )
    assert "DROP TABLE" not in q.sql
    assert q.parameters[0]["value"] == evil


# -- order_by validation -------------------------------------------

def test_order_by_must_be_selected(sl):
    with pytest.raises(SemanticLayerError):
        sl.build_aggregate_query(
            metrics=["revenue"], dimensions=["category"], order_by="unique_users"
        )


def test_order_by_dropoff_metric(sl):
    q = sl.build_aggregate_query(
        metrics=["view_to_cart_dropoff", "views", "carts"],
        dimensions=["category"],
        order_by="view_to_cart_dropoff",
    )
    assert "ORDER BY view_to_cart_dropoff DESC" in q.sql


# -- segments -----------------------------------------------------

def test_high_intent_never_purchase_segment(sl):
    q = sl.build_segment_query("high_intent_never_purchase")
    assert "GROUP BY user_id" in q.sql
    assert "HAVING SUM(is_cart) > 0 AND SUM(is_purchase) = 0" in q.sql
    assert "SUM(is_view) AS views" in q.sql


def test_unknown_segment_raises(sl):
    with pytest.raises(SemanticLayerError):
        sl.build_segment_query("vip_whales")


# -- the three headline MVP questions compile --------------------------

def test_q1_category_view_cart_dropoff_this_week(sl):
    q = sl.build_aggregate_query(
        metrics=["view_to_cart_dropoff", "views", "carts"],
        dimensions=["category"],
        filters=[{"field": "event_date", "op": "last_n_days", "value": 7}],
        order_by="view_to_cart_dropoff",
    )
    assert "GROUP BY 1" in q.sql and "ORDER BY view_to_cart_dropoff DESC" in q.sql


def test_q2_high_intent_never_purchase(sl):
    q = sl.build_segment_query("high_intent_never_purchase")
    assert q.sql.startswith("SELECT")


def test_q3_electronics_vs_apparel_funnel(sl):
    q = sl.build_aggregate_query(
        metrics=["views", "carts", "purchases",
                 "view_to_cart_rate", "cart_to_purchase_rate"],
        dimensions=["category_l1"],
        filters=[{"field": "category_l1", "op": "in",
                  "value": ["electronics", "apparel"]}],
    )
    assert "category_l1 IN UNNEST(@p0)" in q.sql
    assert "SAFE_DIVIDE(SUM(is_cart), SUM(is_view)) AS view_to_cart_rate" in q.sql
