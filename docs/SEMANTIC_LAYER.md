# ShopSense semantic layer — how it works and why

The layer that sits between the Gold star schema and its two consumers (the
Looker dashboard and the GenAI agent), so both ask for a metric by **name**
and get the same number.

---

## 1. The concept

A **semantic layer** is a single, central definition of every business metric
and dimension:

- **metric** — a name, a one-line business meaning, and the exact SQL
  aggregation. `conversion_rate` → `SAFE_DIVIDE(SUM(is_purchase), SUM(is_view))`.
- **dimension** — something you can slice by: category, brand, `event_date`,
  month, top-level category.
- **time grain** — what "daily / weekly / monthly" means as a `GROUP BY`.
- **segment** — a named population that needs a `HAVING` clause, e.g.
  "users who carted but never bought".

It lives in [`semantic/metrics.yaml`](../semantic/metrics.yaml). The builder in
[`semantic/semantic_layer.py`](../semantic/semantic_layer.py) turns a structured
request into BigQuery SQL against one wide view,
[`vw_semantic_events`](../sql/gold/views/vw_semantic_events.sql).

---

## 2. Why ShopSense needs it

**Reason 1 — one number, everywhere.** Without it, the Looker "conversion rate"
tile and the agent's answer to "what's our conversion rate?" are two separate
SQL statements written by two different authors. They drift. The dashboard says
15%, the agent says 18%, and nobody trusts either. The semantic layer makes the
metric formula exist exactly once.

**Reason 2 — the agent cannot be trusted to write SQL over raw tables.** An LLM
pointed at `fact_events` + six dimensions will pick the wrong grain, invent a
join, define "conversion" three ways in one chat, forget the `UNKNOWN` bucket,
and double-count on a fan-out join. Point it at a catalog instead: it chooses
*what* to ask (metric + dimensions + filters), and a deterministic builder
writes the SQL. The maths is already correct; the model only fills in a form.

**Reason 3 — it makes the agent testable.** "Question X → this structured
request → this number" is an assertion you can put in a test. Free-form NL→SQL
is not.

**Reason 4 — safety.** The builder only emits names that exist in the catalog,
and binds every filter value as a BigQuery query parameter (`@p0`). A question
like `brand = "x'); DROP TABLE fact_events; --"` becomes a parameter value, not
SQL.

---

## 3. How it works

```
 User question
      |
      v
 GenAI agent  ── reads ──>  SemanticLayer.describe()   (metric & dimension names)
      |
      v
 structured request  { metrics:[...], dimensions:[...], filters:[...], time_grain }
      |
      v
 SemanticLayer.build_aggregate_query(...)
      |
      v
 CompiledQuery { sql, parameters }   ── deterministic, parameterised
      |
      v
 BigQuery  ──runs against──>  vw_semantic_events   (one row per event, all dims joined)
      |
      v
 rows  ──>  agent summarises in natural language, citing the metric definitions used
```

`vw_semantic_events` is the base view: `fact_events` joined to every dimension
at event grain, with friendly column names, plus `category_l1` (the
top-of-tree category, resolved through `bridge_category_hierarchy`) so
"Electronics vs Apparel" roll-ups work without string-matching a category path.

The builder produces:

- `SELECT` — dimension expressions, then metric expressions, aliased to their
  catalog names
- `FROM vw_semantic_events`
- `WHERE` — filters, every value a `@pN` parameter
- `GROUP BY` — dimension ordinals
- `ORDER BY` — a selected metric/dimension
- `LIMIT` — clamped to a safe maximum

---

## 4. Example — the three MVP questions

**Q1 — "Which categories have the biggest view→cart drop-off this week?"**

```python
sl.build_aggregate_query(
    metrics=["view_to_cart_dropoff", "views", "carts"],
    dimensions=["category"],
    filters=[{"field": "event_date", "op": "last_n_days", "value": 7}],
    order_by="view_to_cart_dropoff",
)
```
```sql
SELECT category_name AS category,
       1 - SAFE_DIVIDE(SUM(is_cart), SUM(is_view)) AS view_to_cart_dropoff,
       SUM(is_view) AS views,
       SUM(is_cart) AS carts
FROM `shop-sense-project.shopsense_analytics_gold.vw_semantic_events`
WHERE event_date >= DATE_SUB(
        (SELECT MAX(event_date) FROM `...vw_semantic_events`), INTERVAL @p0 DAY)
GROUP BY 1
ORDER BY view_to_cart_dropoff DESC
LIMIT 1000
```
"This week" is anchored on the latest date **in the data** (Nov 2019), not the
wall clock.

**Q2 — "Who are our high-intent-but-never-purchase users?"**

```python
sl.build_segment_query("high_intent_never_purchase")
```
→ `GROUP BY user_id HAVING SUM(is_cart) > 0 AND SUM(is_purchase) = 0`.

**Q3 — "What's the funnel for Electronics vs Apparel?"**

```python
sl.build_aggregate_query(
    metrics=["views", "carts", "purchases",
             "view_to_cart_rate", "cart_to_purchase_rate"],
    dimensions=["category_l1"],
    filters=[{"field": "category_l1", "op": "in",
              "value": ["electronics", "apparel"]}],
)
```
`category_l1` rolls every sub-category up to its department, so this compares
the *whole* Electronics tree against the *whole* Apparel tree.

---

## 5. How it fits into ShopSense

```
        Gold star schema  (fact_events + dim_*)
                 |
     +-----------+------------------------------+
     |                                          |
 14 pre-aggregated vw_* views            vw_semantic_events  (1 row / event)
     |                                          |
     v                                          v
 Looker Studio dashboard              semantic/  (metrics.yaml + builder)
                                                 |
                                    +------------+------------+
                                    |                         |
                              Looker (optional,        GenAI agent
                              via the same catalog)     (ADK + BigQuery tool)
                                                              |
                                                          ADK Web UI
```

The pre-aggregated views stay as the fast, purpose-built dashboard tiles. The
semantic layer is the **composable** path — any metric by any dimension — and
is what the agent binds to.

---

## 6. Roadmap

| Step | Status |
|---|---|
| `vw_semantic_events` base view | **done** — deploy via `deploy_views.ps1` |
| `metrics.yaml` catalog + `semantic_layer.py` builder + tests | **done** (21 tests pass) |
| Deploy `vw_semantic_events` + validate row counts tie to `fact_events` | pending (needs BigQuery) |
| ADK agent: tools `get_semantic_catalog` / `build_query` / `run_query` (dry-run then execute) | next |
| Agent prompt + intent → structured-request mapping | next |
| Agent test cases (NL question → expected request / number) | next |
| ADK Web UI wiring | after the agent |

### Extending the catalog

- **New metric** — add an entry under `metrics:` with `expr` (an aggregation
  over `vw_semantic_events`), `type`, and a `description`. No code change.
- **New dimension** — add under `dimensions:` with `expr` (a column of
  `vw_semantic_events`) and `synonyms`. If it needs a new source column, add it
  to `vw_semantic_events.sql` first.
- **New segment** — add under `segments:` with `entity_column` and a `having`
  clause.
