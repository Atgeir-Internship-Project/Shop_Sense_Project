"""
Tests for the ShopSense agent tools.

A fake query runner is injected, so these exercise the model-facing contract
(name resolution, request shaping, error-as-data, forgiving input parsing)
without google-adk, google-cloud-bigquery, or a live warehouse.
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from semantic import SemanticLayer  # noqa: E402
from shopsense_agent import tools  # noqa: E402


class FakeRunner:
    """Stands in for BigQueryRunner - records the compiled query, returns canned rows."""

    def __init__(self, rows=None):
        self.compiled = None
        self.rows = rows if rows is not None else [{"row": 1}]

    def execute(self, compiled):
        self.compiled = compiled
        return {
            "sql": compiled.sql,
            "row_count": len(self.rows),
            "rows": self.rows,
            "truncated": False,
        }


@pytest.fixture
def runner():
    fake = FakeRunner()
    tools.configure(semantic_layer=SemanticLayer.load(), runner=fake)
    yield fake
    tools.configure(semantic_layer=SemanticLayer.load(), runner=FakeRunner())


# -- catalog / explain --------------------------------------------------

def test_get_semantic_catalog_lists_metrics(runner):
    catalog = tools.get_semantic_catalog()
    assert "conversion_rate" in catalog["metrics"]
    assert "category_l1" in catalog["dimensions"]
    assert "high_intent_never_purchase" in catalog["segments"]


def test_explain_metric_returns_formula(runner):
    out = tools.explain_metric("conversion rate")
    assert out["metric"] == "conversion_rate"
    assert "SAFE_DIVIDE" in out["formula"]


def test_explain_unknown_metric_is_error_not_exception(runner):
    assert "error" in tools.explain_metric("gross_margin")


# -- run_metric_query -------------------------------------------------

def test_metric_by_dimension_runs_and_reports_rows(runner):
    out = tools.run_metric_query(metrics=["revenue"], dimensions=["category"])
    assert out["row_count"] == 1
    assert out["metrics_used"] == ["revenue"]
    assert "GROUP BY 1" in runner.compiled.sql


def test_unknown_metric_returns_error_as_data(runner):
    out = tools.run_metric_query(metrics=["click_through_rate"])
    assert "error" in out
    assert runner.compiled is None  # never reached the runner


def test_filters_accepted_as_list_of_dicts(runner):
    tools.run_metric_query(
        metrics=["view_to_cart_rate"],
        dimensions=["category"],
        filters=[{"field": "event_date", "op": "last_n_days", "value": 7}],
    )
    assert "DATE_SUB" in runner.compiled.sql
    assert runner.compiled.parameters[0]["value"] == 7


def test_filters_accepted_as_json_string(runner):
    tools.run_metric_query(
        metrics=["revenue"],
        dimensions=["category_l1"],
        filters='[{"field": "category_l1", "op": "in", "value": ["electronics", "apparel"]}]',
    )
    assert "IN UNNEST(@p0)" in runner.compiled.sql


def test_metrics_accepted_as_comma_string(runner):
    tools.run_metric_query(metrics="revenue, purchases", dimensions="brand")
    assert "AS revenue" in runner.compiled.sql
    assert "AS purchases" in runner.compiled.sql


def test_time_grain_trend_query(runner):
    tools.run_metric_query(
        metrics=["revenue"], time_grain="month", order_by="time", descending=False
    )
    assert "DATE_TRUNC(event_date, MONTH)" in runner.compiled.sql
    assert "ORDER BY month ASC" in runner.compiled.sql


def test_runner_failure_becomes_error_payload(runner):
    class Boom:
        def execute(self, compiled):
            from shopsense_agent.bigquery_runner import BigQueryRunnerError

            raise BigQueryRunnerError("bad query")

    tools.configure(runner=Boom())
    out = tools.run_metric_query(metrics=["revenue"])
    assert out["error"].startswith("query failed")
    assert "sql" in out


# -- run_segment_query ----------------------------------------------

def test_segment_query(runner):
    out = tools.run_segment_query("high_intent_never_purchase")
    assert "HAVING SUM(is_cart) > 0 AND SUM(is_purchase) = 0" in runner.compiled.sql
    assert out["row_count"] == 1


def test_unknown_segment_is_error(runner):
    assert "error" in tools.run_segment_query("whales")


# -- the three MVP questions, end to end through the tools -------------

def test_q1_category_dropoff_this_week(runner):
    out = tools.run_metric_query(
        metrics=["view_to_cart_dropoff", "views", "carts"],
        dimensions=["category"],
        filters=[{"field": "event_date", "op": "last_n_days", "value": 7}],
        order_by="view_to_cart_dropoff",
    )
    assert "error" not in out
    assert "ORDER BY view_to_cart_dropoff DESC" in runner.compiled.sql


def test_q2_high_intent_never_purchase(runner):
    out = tools.run_segment_query("high_intent_never_purchase")
    assert "error" not in out


def test_q3_electronics_vs_apparel_funnel(runner):
    out = tools.run_metric_query(
        metrics=["views", "carts", "purchases", "view_to_cart_rate", "cart_to_purchase_rate"],
        dimensions=["category_l1"],
        filters=[{"field": "category_l1", "op": "in", "value": ["electronics", "apparel"]}],
    )
    assert "error" not in out
    assert "category_l1 IN UNNEST(@p0)" in runner.compiled.sql
