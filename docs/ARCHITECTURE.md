# Inside ShopSense — architecture reference

How the Gold-layer star schema and the Gemini analytics agent are built, and
why every layer earns its place.

A hosted, illustrated version of this document is published at
`docs/architecture.html`. This is the portable copy (readable on GitHub, or
convertible to PDF / Word with `pandoc docs/ARCHITECTURE.md -o architecture.pdf`).

| | |
|---|---|
| Project | `shop-sense-project` |
| Region | `asia-south1` |
| Warehouse | BigQuery |
| Agent | Google ADK · `gemini-3.5-flash` (Vertex AI) |
| Data | 2019-Oct + 2019-Nov, ~109M events (view / cart / purchase only) |

Companion docs: [PIPELINE.md](PIPELINE.md), [GOLD_VIEWS.md](GOLD_VIEWS.md),
[SEMANTIC_LAYER.md](SEMANTIC_LAYER.md), [GENAI_AGENT.md](GENAI_AGENT.md).

---

## 1. The system at a glance

A CSV of raw e-commerce events lands in a bucket. Four stations refine it into a
warehouse built for analytics. A metric catalog gives every number one
definition. A Gemini agent turns plain-English questions into governed queries
against that catalog. A Streamlit page is the window.

Nothing in the chain does the heavy lifting in Python. Each pipeline station
writes a SQL command, hands it to BigQuery, waits, and reads back a summary
row — which is why tens of millions of rows move through in under a minute and
no function ever runs out of memory. The agent is the same idea one level up:
it never writes SQL itself; it picks names from a catalog and a deterministic
builder writes the SQL for it.

```
                    CSV · Cloud Storage  (shopsense-data-lake)
                              |
             gcs_to_bronze  → raw_data_table
                              |  Pub/Sub
        bronze_to_staging  → + batch_id, load_type, source file, ingest time
                              |  Pub/Sub
        staging_to_silver  → clean · quarantine · de-duplicate · number
                              |  Pub/Sub
        silver_to_gold     → STAR SCHEMA  (6 dims + bridge + fact_events)
                              |
              +---------------+------------------------------+
              |                                              |
     14 analytical views                          vw_semantic_events
     (pre-aggregated, one per question)           (1 row / event, all dims joined)
              |                                              |
        Looker Studio dashboard                    semantic layer · metrics.yaml
                                                             |
                                                   ADK agent · Gemini 3.5 Flash
                                                             |
                                                    Streamlit chat UI  ←  you
```

**What was built here.** The two upstream stations (`gcs_to_bronze`,
`bronze_to_staging`) were provided. Everything from **Silver onward was built
for this project**: the Silver transform, the entire Gold star schema, the 14
analytical views, the semantic layer, the GenAI agent, and the UI.
Infrastructure — datasets, buckets, the service account, IAM, Pub/Sub topics —
is Terraform; table *schemas* live in code so a function can create or repair a
table on first run.

---

## 2. The medallion pipeline

The pipeline is deliberately layered rather than one big transform. Each layer
has one job and hands a clean contract to the next.

| Layer | Dataset | Job | Guarantee to the next layer |
|---|---|---|---|
| **Bronze** | `shopsense_analytics` | Raw copy of the CSV, nothing changed | The source is preserved — any later decision can be replayed |
| **Staging** | `shopsense_analytics` | Raw copy + 4 lineage columns per row | Every row knows which file/batch it came from (`batch_id`, `load_type`, source file, ingest time) |
| **Silver** | `shopsense_analytics_silver` | Clean, typed, de-duplicated, numbered | One row per real event, valid types, a stable identity (`surrogate_key`), bad rows quarantined not lost |
| **Gold** | `shopsense_analytics_gold` | Star schema for analytics | Conformed dimensions, one narrow fact table, consistent keys, query performance |

**Why layer it.** A single monolithic transform mixes concerns that fail
differently. Cleaning is row-level and reversible; dimensional modelling is
structural; both want to be tested and re-run independently. Layering also
means a mistake in Gold never touches the cleaned data — you rebuild Gold from
Silver, not from the CSV.

**Event-driven, not scheduled.** A file is finalised in GCS → an event
notification → a Pub/Sub topic → the next Cloud Function wakes. When a station
finishes it publishes its own "batch ready" message. The functions are
decoupled: none imports or calls another. Pub/Sub and Cloud Functions both
retry on failure, so every station is written to be **idempotent** (§7).

---

## 3. What Silver hands to Gold

Gold reads exactly one table:
`shopsense_analytics_silver.transform_data_table`. Its four guarantees explain
most of the Gold design.

1. **Cleaned & typed.** Every column trimmed; `event_type` lower-cased
   (`"VIEW "` → `view`); blank text → real `NULL` for `category_code`,
   `brand`, `user_session`; `event_time` parsed to `TIMESTAMP`; `price` an
   exact `NUMERIC`.

2. **Bad rows quarantined, never deleted.** Rows that fail a rule are *moved*
   to `quarantine_data_table` with a reason — `PRICE_ZERO`, `SESSION_MISSING`,
   `INVALID_TIMESTAMP`, `EXACT_DUPLICATE` — so any exclusion can be reviewed.

3. **Exact duplicates collapsed.** The source has **no ID column**. Identity is
   a `row_hash` — a SHA-256 of the nine cleaned business columns in a fixed
   order. Two rows with the same fingerprint are the same event: keep one,
   quarantine the rest. Measured on the delivered data this removed 2,073 view,
   28,072 cart and only **76 purchase** rows — immaterial to revenue.

4. **A stable identity: `surrogate_key`.** A plain counter — 1, 2, 3, … —
   assigned to each surviving Silver row, computed as `current max + row
   number`, so it **keeps counting across files** and never restarts. Gold
   reuses it directly as `fact_events.event_key`.

**Why this matters for Gold.** Because `surrogate_key` is globally unique and
stable, Gold's fact load can be a simple `MERGE ... ON event_key`: re-processing
a batch matches every row and inserts nothing. And because Silver already
removed exact duplicates, the fact table can never inherit them.

---

## 4. The Gold star schema

Gold is a classic star: one central **fact** table of events, surrounded by
small descriptive **dimension** tables. The fact carries only numeric keys and
measures; everything human-readable lives in a dimension.

```
                          dim_date
                       (one row / day)
                             |  date_key
                             |
   dim_category ---- category_key ---- fact_events ---- product_key ---- dim_product
   (exploded tree)                    (1 row / event)                    (SCD-1)
        |                          _key ×5 · price ·                        |
   bridge_category_hierarchy      is_view/is_cart/is_purchase          resolves its own
   (closure: ancestor→descendant)          |                       category_key / brand_key
                             |  brand_key   |  session_key
                        dim_brand      dim_session
                    (one row / brand)  (rollups / session)

   PARTITION BY date_key · CLUSTER BY category_key, product_key, session_key
   category_id rides along on the fact as a passthrough — never a foreign key
```

**One fact, six satellites.** Every dimension key is a hash of a business value
(§7), so the whole ring can be dropped and rebuilt on every run without
breaking a single key already stored on `fact_events`.

### Build order is a dependency graph

All eight steps run inside *one* BigQuery script that `silver_to_gold` submits.
The order is not arbitrary — each step reads the ones above it.

```
  Silver ──┬─→ 1 · dim_date
           ├─→ 2 · dim_category ──→ 3 · bridge_category_hierarchy
           ├─→ 4 · dim_brand ──┐
           ├─→ 6 · dim_session │
           └──────────────┐    ├─→ 5 · dim_product (SCD-1)
                          │    │
   (Silver + all dims) ───┴────┴─→ 7 · fact_events   (MERGE ON event_key)
                                          │
                                   8 · metrics + integrity checks
```

**Why order matters.** `fact_events` resolves its `category_key` / `brand_key`
by joining to the dimensions, so they must exist first. If a dimension build
fails, the function marks the batch `FAILED` and stops — it does not load a
fact with dangling keys.

---

## 5. Every dimension, and why it exists

### dim_date — one row per calendar day

Generated with `GENERATE_DATE_ARRAY` over the min/max `event_time` in Silver.
Columns: `date_key` (the `DATE` itself — no surrogate needed), `day`, `week`
(ISO), `month`, `month_name`, `quarter`, `year`, `day_of_week`, `is_weekend`.

**Why a whole table for dates.** Every "daily / weekly / monthly" question and
every "is conversion higher on weekends" question becomes a plain join and
`GROUP BY` instead of scattered `EXTRACT()` logic re-derived in each query. The
attributes are computed once, here.

### dim_category — a variable-depth tree, flattened

`category_code` is a dotted path of *unpredictable* depth: `electronics`,
`electronics.smartphone`, `appliances.kitchen.oven`. The build takes every
distinct non-null code and **explodes each into all of its prefixes**,
de-duplicated across the whole set. `"a.b.c"` contributes three nodes: `a`,
`a.b`, `a.b.c`. Each node gets:

- `category_key` = `FARM_FINGERPRINT(full path)`
- `parent_category_key` = hash of the path minus its last segment (`NULL` at the top)
- `level_number` = depth, `is_leaf` = has no children, `category_name` = last segment

Plus one `UNKNOWN` row at key `-1`. On the delivered data that is **~159 real
nodes + 1 = ~160 rows**.

**Why keyed on the code, not `category_id`.** `category_id` and `category_code`
are **not 1:1** — the same textual code appears under multiple numeric ids. The
*code* is the meaningful hierarchy, so it is the key. `category_id` is kept on
the fact as an informational passthrough only, never a foreign key. And because
depth varies, the model cannot assume "level 1, level 2, level 3" — exploding
prefixes handles any depth.

### bridge_category_hierarchy — the closure table

A recursive query over `dim_category` that produces every `(ancestor,
descendant, hierarchy_level)` pair, including each node paired with itself at
level 0.

**Why it is worth a table.** "Everything under `electronics`" becomes one join
— no fragile `LIKE 'electronics%'` string matching that would also catch
`electronics_repair`. It is what lets the semantic layer expose a single
`category_l1` (top-of-tree) dimension and answer "Electronics vs Apparel" as a
clean roll-up.

### dim_brand — one row per brand

Distinct non-null `brand`, key = `FARM_FINGERPRINT(brand)`, plus `UNKNOWN` at
`-1`. Small, descriptive, the anchor for every brand-level metric.

### dim_product — SCD Type 1, one row per product

A product appears in millions of events, sometimes with a `NULL` brand on one
event and a real brand on another. The build **consolidates** per `product_id`,
preferring a non-null `category_code` / `brand` from *anywhere* in that
product's events, then resolves those to `category_key` / `brand_key` (falling
back to `-1`). `product_key` = `FARM_FINGERPRINT(product_id)`.

**Why SCD-1 (overwrite, no history).** This project asks "what does this product
convert at", not "what category was it in last March". Type 1 keeps the
dimension one row per product and the joins simple. If product history ever
mattered, this is the one table that would change.

### dim_session — rollups per visit

One row per `user_session` with `session_start_time` / `session_end_time`
(MIN/MAX event time), `event_count`, `has_purchase`, and `is_multi_user` (more
than one `user_id` seen on the session).

**Why pre-compute these.** Session-grain questions — how long visits run, how
many sessions convert, how often a session is shared — are answered by reading
one small table instead of re-aggregating the fact every time.

---

## 6. The fact table

The grain is **one row per user event** (a view, a cart, or a purchase). Every
metric in the whole platform rolls up from here.

| Column group | Columns | Purpose |
|---|---|---|
| Identity | `event_key` | = Silver `surrogate_key`. The MERGE key. |
| Foreign keys | `date_key`, `product_key`, `category_key`, `brand_key`, `session_key` | Numeric hashes pointing at the dimensions |
| Passthrough | `user_id`, `category_id`, `event_time`, `event_type`, `batch_id` | Carried for filtering / lineage; `category_id` is *not* a key |
| Measures | `price`, `event_count` (const 1), `is_view`, `is_cart`, `is_purchase` | Everything you `SUM()`. `SUM(event_count)` = event total = `is_view + is_cart + is_purchase` |

`PARTITION BY date_key` and `CLUSTER BY category_key, product_key, session_key`:
a "last 7 days by category" query scans one week of one cluster, not 109M rows.

**Why the 1/0 flag columns.** `is_view` / `is_cart` / `is_purchase` turn the
funnel into arithmetic. `SUM(is_cart) / SUM(is_view)` is the view→cart rate; no
`CASE`, no self-join, and it aggregates at any grain for free. Every view and
every metric in the catalog is built on these three sums plus `SUM(price)`.

---

## 7. Five decisions that shape the whole load

**1. Hash keys, so dimensions can be rebuilt every run.** Every dimension key
is `FARM_FINGERPRINT` of its business value — `"electronics.smartphone"` becomes
the same integer every time, forever. So `dim_*` tables are `CREATE OR REPLACE`
— wiped and rebuilt on every run — and the keys already stored on `fact_events`
still resolve, because the key is a pure function of the value. No append means
no accumulated duplicates and no coordination.

**2. Only `fact_events` uses MERGE.** It is the one table that *grows* by
appending new events, so it is the one place a Pub/Sub or Cloud Function retry
could double-insert. `MERGE ... ON event_key WHEN NOT MATCHED THEN INSERT` — a
re-run matches every row and inserts zero.

**3. UNKNOWN members, never a silent drop.** A `NULL` `category_code` or `brand`
maps to key `-1`, which is a real, labelled row (`'UNKNOWN'`) in the dimension.
A fact row is never lost to a join. `fk_resolution_failures = 0` is a checked
invariant on every run.

**4. Revenue = `SUM(price)` over purchase events.** There is no quantity or
order-total column anywhere in the source. `event_count` is a constant 1 — a
grain marker, not units. So one purchase event contributes its `price` once.
Verified against the data: only 76 exact-duplicate purchase rows existed, so
this is not materially undercounting.

**5. Idempotency at every hop.**

- Each function first checks its control table — batch already `SUCCESS` → stop.
- The Silver transform runs inside a transaction — a failure rolls back with nothing half-written.
- Gold dimensions are deterministic rebuilds; the fact is a MERGE. Re-run → identical result.

---

## 8. Data quality & orchestration

Three **control tables** — `ingestion_control`, `ingestion_transform_control`,
`ingestion_insight_control` — each hold one row per batch that moves
`PROCESSING → SUCCESS` (or `FAILED`, which a retry flips back). They also store
every run metric: rows in, duplicates removed by reason, rows written per
table, foreign-key failures, duplicate event keys.

After the Gold build, step 8 of the script computes integrity checks in the
same pass:

- `fk_resolution_failures` — fact rows whose `*_key` doesn't resolve to a dimension (expected 0)
- `duplicate_event_keys` — `COUNT(*) − COUNT(DISTINCT event_key)` (expected 0)
- `fact_events_total == silver_rows` once every batch is in
- `dim_category` row count inside a sanity band (~159) — drift is logged as a warning

A dedicated rule engine and Gold-layer alerting are the honest next step; today
the checks are computed and recorded, but run and reviewed by hand.

---

## 9. The analytical views

On top of the star sit 14 `CREATE OR REPLACE VIEW` definitions. Twelve answer
one dashboard question each; three form an executive Overview set
(`vw_business_summary`, `vw_category_daily_summary`, `vw_product_revenue`).
Full catalog and per-view detail is in [GOLD_VIEWS.md](GOLD_VIEWS.md).

**Rules every view follows:**

- **Aggregate first, join second.** Each view collapses the fact to its target
  grain in a CTE *before* touching a dimension — the expensive scan produces a
  small result, and window functions run on that.
- **Aggregate (macro) conversion.** `carts / views`, `purchases / carts` as
  event-count ratios. The schema has no cart/order id linking one specific view
  to one specific later cart, so a session-sequential funnel is not possible —
  this is the standard category/product-level definition.
- **`SAFE_DIVIDE` everywhere** — a zero denominator yields `NULL`, never a
  crash or a fake 0%.
- **Thresholds are percentile-based and exposed** — a "top quartile" cut ships
  the raw percentile as a column; nothing is a hidden magic number.
  Small-sample floors (e.g. "≥ 30 views to be ranked") keep a 1-view fluke off
  a leaderboard.

**`vw_semantic_events` — the base view.** The one wide, denormalised,
one-row-per-event view: `fact_events` joined to every dimension, with friendly
column names and a `category_l1` resolved through the bridge. It is **not a
dashboard tile** — it is the single surface every agent query is compiled
against, so metric maths lives in the catalog once and is never re-invented per
question.

---

## 10. The semantic layer

Two files sit between the warehouse and its consumers. Full detail in
[SEMANTIC_LAYER.md](SEMANTIC_LAYER.md).

### metrics.yaml — the catalog

| Entry | Count | Each one carries |
|---|---|---|
| **metrics** | 15 | name, label, the exact aggregation `expr` over `vw_semantic_events`, a type (`additive` / `distinct` / `ratio`), and a one-line business description |
| **dimensions** | 14 | name, column `expr`, type, and synonyms (`department` → `category_l1`) |
| **time_grains** | 4 | `day` / `week` / `month` / `quarter` → a `DATE_TRUNC` group column |
| **segments** | 1 | entity-grain populations that need a `HAVING` clause (`high_intent_never_purchase`) |

### semantic_layer.py — the builder

`SemanticLayer.load().build_aggregate_query(metrics, dimensions, filters,
time_grain, order_by, limit)` returns a `CompiledQuery(sql, parameters)`. Its
guarantees, all covered by 21 tests:

- Only names that exist in the catalog reach the SQL — an unknown metric raises, it doesn't guess.
- Every filter value is bound as a BigQuery `@pN` parameter — `brand = "x'); DROP TABLE…"` becomes a parameter value, not SQL.
- `last_n_days` anchors on `MAX(event_date)` in the data, never `CURRENT_DATE` — the data is 2019.

```python
# "biggest view→cart drop-off this week"
sl.build_aggregate_query(
    metrics=["view_to_cart_dropoff", "views", "carts"],
    dimensions=["category"],
    filters=[{"field": "event_date", "op": "last_n_days", "value": 7}],
    order_by="view_to_cart_dropoff",
)
```

**Why not let the agent query the 14 views, or raw tables.** The 14 views are
*answers* — each frozen at one grain, one metric set. The agent gets questions
they were never shaped for ("conversion by brand by week"). Pointed at raw
`fact_events`, an LLM invents joins, picks the wrong grain, and defines
"conversion" three ways in one chat. Pointed at a catalog, it only chooses
*what* to ask; a deterministic builder writes the SQL. Same reason the
dashboard and the agent must share this layer: so both return the same
"conversion rate" by construction.

---

## 11. The GenAI analyst

Built on **Google ADK** (Agent Development Kit) — the Python framework that
wraps an LLM, its tools, and a session. The model is **`gemini-3.5-flash`**,
served through **Vertex AI**. Full detail in [GENAI_AGENT.md](GENAI_AGENT.md).

**Why this model.** The task is structured tool-use, not long-form reasoning —
the Flash tier is fast, inexpensive, and reliable at it. `3.5` specifically for
its higher request rate limits: an earlier build on `2.5-flash` hit a
per-minute `429` after roughly five questions, because each question is 2–3
model calls. The model id is a single env var (`SHOPSENSE_AGENT_MODEL`).

### The four tools

| Tool | Does |
|---|---|
| `get_semantic_catalog` | Returns every metric / dimension / segment name (also rendered straight into the system prompt, so the agent rarely needs to call it) |
| `explain_metric` | Returns one metric's formula + meaning — for "how do you define conversion rate?" |
| `run_metric_query` | Takes metric / dimension / filter *names* → semantic layer compiles the SQL → runs it → returns `{sql, rows, row_count}` or `{error}` |
| `run_segment_query` | Same, for a named `HAVING` population |

Errors are returned *as data*, not raised — so the model can read "unknown
metric 'foo'" and correct itself. Inputs are parsed forgivingly (a list, a
comma string, or JSON text all work).

### The hard rules in the system prompt

- **Never state a number that didn't come from a tool** in this conversation. No estimates.
- You do not write SQL — you pick names; the tools build it.
- Only catalog names. If the question needs something absent, say what's missing.
- Data is Oct–Nov 2019. "This week" = the last 7 days present in the data.

### The request flow

```
  question ─→ Gemini 3.5 ──(names)──→ semantic layer ─→ SQL + @params ─→ BigQuery runner
             (catalog in prompt)                                          (dry-run ✓ · execute)
                   ▲                                                              │
                   └──────────────────────── rows ────────────────────────────────┘
                   │
          natural-language answer

  left of the "names" arrow: the model chooses catalog names.
  right of it: deterministic SQL. The model never emits SQL.
```

**The boundary.** Everything the model produces is a set of catalog names. It
never emits SQL, so it cannot hallucinate a join, a grain, or a metric formula.
What it *can* get wrong — picking the wrong metric — is exactly what the eval
set checks.

### Agent test cases

`genai/eval/eval_questions.yaml` holds 14 canonical questions, each with the
tool call a correct agent should make and the shape of a good answer.
`test_eval_questions.py` asserts every one compiles to valid SQL;
`test_tools.py` adds 15 tests on name resolution, request shaping, and
error-as-data — all with a fake query runner, so **30 agent tests run with no
ADK, no BigQuery, and no model**.

### Auth

Vertex AI + Application Default Credentials (`gcloud auth application-default
login`), with `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION=global`. A stale `GOOGLE_APPLICATION_CREDENTIALS`
pointing at a deleted service-account key for another project will override ADC
and must be unset.

---

## 12. The chat UI

A deliberately plain Streamlit page: ask a question, get an answer. No
suggested questions, no stored history — one thread per browser session,
cleared on refresh. Full detail in [../frontend/README.md](../frontend/README.md).

`frontend/services/agent_client.py` is the **only** seam between UI and
backend. `ask_shopsense_agent(question, session_id)` runs the ADK agent —
either in-process (an ADK `Runner` in the Streamlit process, the default) or
over HTTP to a separate `adk api_server` — then reads the agent's event stream:
the final model text is the `answer`; the `run_metric_query` tool response
gives the `sql` and `rows`.

The page then renders: the answer → a collapsed *View generated SQL* → KPI
cards for a single-row result or a Plotly chart + table for many rows → a "no
matching data" state → a friendly error card. **The frontend never runs SQL
from user input** — it only displays what the trusted backend returns. 14
frontend tests cover the normalisation and rendering logic with no Streamlit or
network.

---

## 13. One question, through every layer

> "Which categories are seeing the biggest drop-off between view and cart this week?"

| Layer | What happens |
|---|---|
| UI | Question + a session id go to `ask_shopsense_agent`. |
| Agent | Gemini, with the catalog already in its prompt, emits `run_metric_query(metrics=["view_to_cart_dropoff","views","carts"], dimensions=["category"], filters=[{event_date, last_n_days, 7}], order_by="view_to_cart_dropoff")`. |
| Semantic layer | Compiles it: `SELECT category_name, 1 - SAFE_DIVIDE(SUM(is_cart), SUM(is_view)) … FROM vw_semantic_events WHERE event_date >= DATE_SUB((SELECT MAX(event_date) …), INTERVAL @p0 DAY) GROUP BY 1 ORDER BY …` with `@p0 = 7`. |
| Runner | Dry-runs the SQL to validate, then executes with the bound parameter. |
| BigQuery | `vw_semantic_events` resolves to `fact_events` — partitioned by `date_key`, so only the last week is scanned — joined to `dim_category` and `dim_date`. |
| Agent | Reads the rows, writes: "`electronics.telephone` has the highest view→cart drop-off this week at 96.1% — 812K views, 32K carts…" |
| UI | Answer text, a bar chart of drop-off by category, the table, and the SQL behind a disclosure. |

### Why every layer is there

- **Medallion** — so cleaning, modelling and analytics fail and re-run independently.
- **Star schema** — so 109M events aggregate fast and every join is conformed.
- **Hash keys** — so dimensions rebuild freely without breaking stored facts.
- **The 14 views** — fast, fixed answers for the dashboard.
- **The semantic layer** — one definition of every metric, shared by dashboard and agent.
- **The agent** — plain-English access, grounded so it can't invent numbers.
- **The UI** — a window that only ever shows what the trusted backend computed.

---

## Repository map

```
cloud_functions/
  gcs_to_bronze/            provided
  bronze_to_staging/        provided
  staging_to_silver/        Silver transform (built here)
  silver_to_gold/           Gold star-schema build (built here)
    gold_sql.py             the 8-step BigQuery script
    schemas.py              Gold table schemas
sql/gold/views/             14 analytical views + vw_semantic_events + deploy_views.ps1
semantic/
  metrics.yaml              the metric catalog
  semantic_layer.py         the deterministic SQL builder
  run_query.py              ad-hoc CLI runner
genai/shopsense_agent/      the ADK agent (agent.py, tools.py, bigquery_runner.py, prompts.py)
genai/eval/eval_questions.yaml   14 agent eval questions
frontend/                   the Streamlit chat UI
docs/                       PIPELINE · GOLD_VIEWS · SEMANTIC_LAYER · GENAI_AGENT · ARCHITECTURE
Terraform/                  infrastructure
```

**Tests:** 65 across the project — 21 semantic, 30 agent, 14 frontend — plus
the cloud-function unit and integration suites.
