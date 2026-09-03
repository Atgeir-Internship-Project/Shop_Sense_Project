# ShopSense semantic layer

The single definition of what every business metric **means**. The Looker
dashboard and the GenAI agent both resolve metrics through here, so
"conversion rate" is the same number everywhere.

## Files

| File | What it is |
|---|---|
| `metrics.yaml` | The catalog — metrics, dimensions, time-grains, segments, with the exact SQL expression and business description for each. Edit this to change a definition. |
| `semantic_layer.py` | Loads the catalog and compiles a structured request into deterministic, parameterised BigQuery SQL. |
| `../sql/gold/views/vw_semantic_events.sql` | The one wide event-grain view every compiled query runs against. |
| `tests/` | Unit tests for the builder (no BigQuery needed). |

## How the agent uses it

The agent never writes raw SQL. It:

1. reads `SemanticLayer.describe()` to know the available metric / dimension names,
2. maps the user's question to a **structured request** (metric names + dimension
   names + filters + optional time-grain),
3. calls `build_aggregate_query(...)` / `build_segment_query(...)` to get SQL,
4. executes that SQL on BigQuery and summarises the rows.

Because step 3 only ever emits names that exist in the catalog, and binds every
filter value as a query parameter, a natural-language question can neither
invent a metric formula nor inject SQL.

## Quick start

```python
from semantic import SemanticLayer

sl = SemanticLayer.load()

# "Which categories have the biggest view->cart drop-off this week?"
q = sl.build_aggregate_query(
    metrics=["view_to_cart_dropoff", "views", "carts"],
    dimensions=["category"],
    filters=[{"field": "event_date", "op": "last_n_days", "value": 7}],
    order_by="view_to_cart_dropoff",
)
print(q.sql)          # parameterised BigQuery SQL
print(q.parameters)   # [{"name": "p0", "type": "INT64", "value": 7}]
```

Running the compiled query (the agent / a Cloud Function does this):

```python
from google.cloud import bigquery

client = bigquery.Client(project="shop-sense-project")
params = []
for p in q.parameters:
    if p["type"].startswith("ARRAY<"):
        params.append(bigquery.ArrayQueryParameter(
            p["name"], p["type"][6:-1], p["value"]))
    else:
        params.append(bigquery.ScalarQueryParameter(
            p["name"], p["type"], p["value"]))
rows = client.query(
    q.sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
).result()
```

## The request shape

`build_aggregate_query`:

| arg | meaning |
|---|---|
| `metrics` | one or more metric names / synonyms (required) |
| `dimensions` | names to slice by (`GROUP BY`) |
| `filters` | list of `{"field", "op", "value"}` — ops: `eq`, `ne`, `in`, `gte`, `lte`, `between`, `contains`, `last_n_days` |
| `time_grain` | `day` / `week` / `month` / `quarter` — adds a truncated-date group column |
| `order_by` | a selected metric or dimension (or `"time"` for the grain) |
| `limit` | clamped to `max_row_limit` (10000) |

`build_segment_query("high_intent_never_purchase")` — entity-grain populations
that need a `HAVING` clause.

## Relative dates

The dataset is historical (2019-10 / 2019-11). `last_n_days` anchors on
`MAX(event_date)` in the data, **not** `CURRENT_DATE` — "this week" means the
last 7 days that exist in ShopSense, not the last 7 calendar days.

## Tests

```powershell
pip install -r tests/requirements-dev.txt
python -m pytest semantic/tests/ -q      # run from the repo root
```
