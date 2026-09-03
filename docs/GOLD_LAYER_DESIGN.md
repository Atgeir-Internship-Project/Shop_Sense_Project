# The Gold layer: design, build, and the alternatives not taken

This document explains the Gold **star schema build** itself — the
`silver_to_gold` Cloud Function that turns cleaned Silver events into
`fact_events` + 6 dimension tables. For the **BI/dashboard views** built on
top of Gold (`vw_*`), see [GOLD_VIEWS.md](GOLD_VIEWS.md). For the pipeline as
a whole, see [PIPELINE.md](PIPELINE.md).

Every major decision below is presented the same way: what was built, what
the realistic alternative was, and why the alternative lost. Nothing here is
the only correct way to do this — it's the specific set of trade-offs made
for this project's shape (100M+ row batches, a small team, BigQuery as the
only compute engine).

---

## 1. Where Gold sits and what triggers it

```
staging_to_silver  --publish-->  shopsense-silver-loaded (Pub/Sub topic)
                                          |
                                          v
                                  silver_to_gold  (this layer)
                                          |
                                          v
                     shopsense_analytics_gold.{dim_*, fact_events}
```

A message arrives with `{batch_id, source_file_name, load_type}` whenever
Silver finishes a batch. `silver_to_gold` does **not** filter Silver down to
just that batch, though — every run rebuilds the dimensions from, and
re-MERGEs the fact table against, the **entire** `transform_data_table`. The
message exists only to (a) trigger a rebuild and (b) key the
`ingestion_insight_control` row for that rebuild's metrics. See §4.6 for why
"reprocess everything, every time" was chosen over batch-scoped incremental
loading.

**Files:** `cloud_functions/silver_to_gold/{main,control,tables,gold_sql,build}.py`

## 2. The orchestration flow (`main.py`)

```
1. decode the Pub/Sub message
2. ensure_gold_tables()          <- ensure fact_events + control table have
                                     a schema BEFORE anything queries them
3. already_succeeded(batch_id)?  <- stop if this batch's rebuild already ran
4. start_processing(batch_id)    <- claim it: PROCESSING
5. run_gold_build()              <- the one big BigQuery script (§3)
6. finish_success(batch_id, metrics)
```

Step 2 exists for a very concrete reason: Terraform creates
`fact_events`/`ingestion_insight_control` with **no columns at all**, and
`CREATE TABLE IF NOT EXISTS` silently does nothing to a table that already
exists — so the schema has to be retrofitted via the BigQuery client
(`tables.py`) before the control-table query in step 3 can even run. This
was a real bug hit during development (see PIPELINE.md's debugging history)
and fixed by moving the "ensure schema" step ahead of the first query that
needs it.

## 3. The build itself — one BigQuery script, in dependency order

`gold_sql.py` generates a single multi-statement script; `build.py` submits
it once and reads back one row of metrics. The Cloud Function never touches
row-level data — it just waits for BigQuery.

| Step | Table | How |
|---|---|---|
| 1 | `dim_date` | `GENERATE_DATE_ARRAY` over the min/max `event_time` in Silver |
| 2 | `dim_category` | explode every distinct `category_code` into its prefix levels; key = `FARM_FINGERPRINT(path)` |
| 3 | `bridge_category_hierarchy` | `WITH RECURSIVE` closure over `dim_category` |
| 4 | `dim_brand` | distinct `brand` + one `UNKNOWN(-1)` row |
| 5 | `dim_product` | `GROUP BY product_id`, preferring a non-NULL category/brand from anywhere in the group |
| 6 | `dim_session` | `GROUP BY user_session` — start/end time, event count, `has_purchase`, `is_multi_user` |
| 7 | `fact_events` | `MERGE ... ON event_key WHEN NOT MATCHED THEN INSERT` |
| 8 | metrics `SELECT` | row counts + FK-orphan check + duplicate-key check, in one row |

Steps 1–6 are `CREATE OR REPLACE TABLE` — full, deterministic rebuilds.
Step 7 is the one `MERGE`, and it's the only step that can be re-run safely
without duplicating anything (see §4.1 and §4.2 for why).

---

## 4. Design decisions, alternatives, and why

### 4.1 Full rebuild for dimensions, MERGE only for the fact

**Chosen:** the 6 dimension/bridge tables are dropped and recreated from
scratch every run (`CREATE OR REPLACE TABLE ... AS SELECT`). Only
`fact_events` uses `MERGE`.

**Alternative considered:** treat every dimension like the fact table —
`MERGE ... WHEN NOT MATCHED THEN INSERT` with sequential keys
(`MAX(key)+ROW_NUMBER()`, exactly like Silver's `surrogate_key`), so nothing
is ever fully rebuilt.

**Why full rebuild won:** a dimension key here is `FARM_FINGERPRINT` of the
business value (see §4.3) — a pure, stateless function of the input. That
means re-deriving the *entire* dimension from scratch always produces the
exact same rows with the exact same keys. There is no "append" happening, so
there is nothing that could be duplicated. The incremental-MERGE alternative
would need the same idempotency machinery as the fact table (state,
concurrency handling, `WHEN MATCHED` update logic for SCD1 changes) for
*five more tables*, for close to zero benefit — the dims are small
(hundreds to hundreds-of-thousands of rows) and a full rebuild is cheap. The
fact table is different: it's the one thing that structurally only ever
*grows*, so it's the one place `MERGE` earns its complexity.

### 4.2 `MERGE ... ON event_key`, not `TRUNCATE + INSERT` or a transaction-guarded DELETE+INSERT

**Chosen:** `fact_events` is `CREATE TABLE IF NOT EXISTS` once, then only
ever `MERGE`d into, keyed on `event_key` (Silver's `surrogate_key`, cast to
STRING).

**Alternative considered:** what Silver itself does for its own idempotency —
wrap `DELETE FROM fact_events WHERE batch_id = @batch_id` + a fresh `INSERT`
in a transaction, so a retried batch's old (possibly partial) rows are
cleared before being replaced.

**Why `MERGE` won here:** Silver needs the delete-then-insert pattern because
a batch can be *retried after a partial failure* and Silver's identity
(`row_hash`) doesn't change between the two attempts. Gold's fact load reads
the **whole** Silver table on every run, not one batch — there's no
"this batch's rows" subset to delete and replace. `MERGE ... WHEN NOT
MATCHED` is simpler and correct for that shape: any row already present
(by `event_key`) is left alone, anything new is added. It was also the
approach the original Gold spec asked for explicitly, having already ruled
out `CREATE OR REPLACE` for exactly the reason above.

*(A real bug surfaced during testing that's worth knowing about: truncating
Silver without also truncating `fact_events` resets Silver's surrogate-key
counter, so newly-loaded rows get **recycled** `event_key` values that
already exist in the untouched `fact_events` — the MERGE then (correctly, by
its own logic) treats them as already-loaded and inserts nothing. That's not
a MERGE bug; it's a violation of the assumption that `surrogate_key` values
are never reused. See PIPELINE.md's debugging history for the full story.)*

### 4.3 `FARM_FINGERPRINT` hash keys, not sequential integers or natural keys

**Chosen:** every dimension key (`category_key`, `brand_key`, `product_key`,
`session_key`) is `FARM_FINGERPRINT(business value)` — a deterministic
64-bit hash.

**Alternatives considered:**
- **Sequential integers** (`ROW_NUMBER()` / `MAX+ROW_NUMBER()`) — rejected
  because they're only stable if the dimension is never fully rebuilt (see
  §4.1); combined with `CREATE OR REPLACE`, a category could get a different
  key on every run, silently breaking every `fact_events` row that already
  points at the old one.
- **`GENERATE_UUID()`** — rejected for the same reason (non-deterministic,
  changes every run) plus it doesn't fit a `CLUSTER BY` column well.
- **The natural value itself as the key** (e.g. `category_code` STRING,
  `user_session` STRING) — a real, simpler option, but rejected because (a)
  the target schema specified `INT64` keys, (b) `user_session` is a long
  string, bad for `fact_events`'s `CLUSTER BY`, and (c) `dim_category`'s
  *synthetic* parent nodes (a category that only exists as an inferred
  ancestor, never as a real `category_code` in the data) have no natural id
  to use.

**Why the hash won:** it's the only option that is simultaneously (a)
deterministic — the same input always produces the same key, forever, which
is what makes the `CREATE OR REPLACE` rebuild in §4.1 safe — and (b) requires
zero shared state or lookup to compute; `fact_events` can compute
`FARM_FINGERPRINT(s.category_code)` directly from a Silver row with no join
needed to "find" the key first.

*(The trade-off: hash keys carry no meaning in their sign or magnitude — a
negative key is exactly as valid as a positive one; only the literal `-1`
sentinel is special. This surprised people during review and is documented
in detail in the Q&A history, but it's a cosmetic surprise, not a
correctness issue.)*

### 4.4 `dim_category` keyed by `category_code`, never `category_id`

**Chosen:** `dim_category`'s grain and key are purely the dotted
`category_code` path. `category_id` never appears in any dimension — it
rides along in `fact_events` only as an informational passthrough column.

**Alternative considered:** key `dim_category` by `category_id`, the more
"obvious" integer id sitting right there in the source data.

**Why `category_code` won:** profiling found up to 23 different
`category_id` values mapping to the *same* `category_code` text (e.g.
`"apparel.shoes"`), while every `category_id` maps to exactly one
`category_code`. Keying by `category_id` would have silently created
duplicate dimension rows for what is really one category, and made the
hierarchy explosion (§4.5) incoherent (which `category_id` would a
synthetic parent node even use?). `category_code` is the only value that
is actually 1:1 with "what category is this."

### 4.5 A closure/bridge table for the hierarchy, not string matching or a fixed number of level columns

**Chosen:** `dim_category` explodes every code into its prefix levels
(`"a.b.c"` → nodes `a`, `a.b`, `a.b.c`), and `bridge_category_hierarchy` is a
pre-computed closure table (every ancestor→descendant pair, at every
distance) built with `WITH RECURSIVE`.

**Alternatives considered:**
- **String matching at query time** (`WHERE category_code LIKE 'electronics%'`)
  — works for this exact 3-level, dot-delimited scheme, but breaks the moment
  a category name itself contains a dot, or the delimiter changes, and can't
  express "roll up N levels" cleanly.
- **Fixed `level_1`/`level_2`/`level_3` columns on `dim_category`** — a
  common alternative for hierarchies, but only works when depth is
  constant; this data has 2-, 3-, and one 4-level path, so a fixed number of
  columns would need NULLs for shallower categories and still couldn't
  answer "everything under `electronics`" without... the same recursive
  logic the bridge table already encodes once.

**Why the bridge table won:** it's built once (during the Gold rebuild, on a
~150-node table, not the 100M-row fact table) and turns every future roll-up
question into a single plain join — `JOIN bridge ON ancestor_category_key =
<electronics's key>` — with no recursion, no string parsing, and no
assumption about a fixed depth, at query time.

### 4.6 Reprocess the whole Silver table every run, not just the new batch

**Chosen:** every Gold run rebuilds all 6 dimensions from, and re-MERGEs
against, the **entire** `transform_data_table` — not filtered to the
triggering batch.

**Alternative considered:** scope the fact MERGE's source query to
`WHERE batch_id = @batch_id`, processing only the newly-arrived rows —
mirroring exactly how Silver scopes its own transform to one batch.

**Why full reprocessing won (for now):** the project's own validation
requirement was that `fact_events` row count must equal Silver's row count
*exactly* — the simplest way to guarantee that invariant is to always
compare against all of Silver, not trust that every batch's message was
delivered and processed. It also means a dimension member introduced in
batch 3 (a brand-new brand, say) is visible even if some earlier batch's
Gold run happened to run first.

**The real cost, and when to revisit this:** every run re-scans the full
fact-eligible Silver table and re-MERGEs it, even though `MERGE` inserts
zero new rows for data it's already seen. At October's ~42M rows this is
fine; combined with November's ~67M rows it becomes a genuinely large
job per run, and it's why the Cloud Function's 540s timeout is a live risk
(documented in PIPELINE.md). If Silver batches become frequent (e.g. hourly
incremental files instead of weekly), the fact MERGE should be re-scoped to
`WHERE batch_id = @batch_id` — the dimensions can safely stay full-rebuild
regardless (they're cheap), only the fact MERGE's source needs to change.

### 4.7 `event_key` as STRING, not INT64

**Chosen:** `fact_events.event_key = CAST(surrogate_key AS STRING)`.

**Alternative considered:** keep it INT64, matching Silver's
`surrogate_key` type directly — no cast needed anywhere.

**Why STRING won:** it was the literal spec (`event_key STRING`), and the
reasoning holds up independently: `event_key` is only ever compared with
`=` (the MERGE condition, the duplicate check) — never summed, averaged, or
sorted numerically — so typing it as an opaque identifier is honest about
its role, and it decouples Gold's fact grain from Silver's specific
key-generation mechanism (today a sequential counter; if that ever changed,
`event_key` wouldn't need to). The measured cost — a marginally larger,
marginally slower join in the one recurring place it's compared, the nightly
MERGE — was judged not worth deviating from the spec for. See the Q&A
history for the full trade-off table; this was revisited explicitly and
INT64 was rejected as "correct but not worth a migration."

### 4.8 A Python-generated SQL script, submitted via the BigQuery client — not a stored procedure, not dbt

**Chosen:** `gold_sql.py` builds one big SQL string in Python; the Cloud
Function submits it with `google-cloud-bigquery` and reads back a metrics
row.

**Alternatives considered:**
- **A BigQuery stored procedure** (`CREATE PROCEDURE ... CALL proc()`) —
  would move the same script into a routine object living inside BigQuery
  itself, callable from the console without touching the Cloud Function.
- **dbt** (or a similar SQL-first transformation tool) — models per table,
  built-in testing/lineage, scheduled runs.

**Why the current approach won:** the original spec asked explicitly for a
Python orchestrator that submits BigQuery SQL jobs — matching the same
pattern already used for Bronze and Silver, so there's one consistent
architecture across all three layers rather than three different ones. A
stored procedure would duplicate the same SQL in a second place that needs
its own deployment step, for no new capability the project currently needs
(nobody needs to `CALL` a Gold rebuild from the console independent of the
Pub/Sub trigger). dbt is a legitimate alternative architecture for a
project like this, but it's a different paradigm entirely (SQL-first, no
Python layer) — adopting it would mean redesigning the whole pipeline, not
extending this one function.

### 4.9 Schema defined in Python code, retrofitted onto Terraform's schemaless tables

**Chosen:** Terraform creates the 8 Gold tables with no columns at all; the
actual schema lives in `schemas.py` and is applied by the BigQuery client
(`tables.py`) the first time each table is touched.

**Alternative considered:** define the full schema (columns, types,
partitioning, clustering) in Terraform itself, so `terraform apply` creates
fully-formed tables and the Python code never needs to check or repair
anything.

**Why the current split won:** this was an explicit decision by the
project's owners — Terraform intentionally does *not* own the schema here,
so it can be defined and versioned alongside the transformation logic that
depends on it, in the same language and the same pull request. The
trade-off is real and was hit during development: `CREATE TABLE IF NOT
EXISTS` does nothing to a table Terraform already created empty, so
`tables.py` has to explicitly check for an empty schema and patch it in —
and for `fact_events` specifically, partitioning can't be added after the
fact, so a schemaless-and-unpartitioned placeholder has to be dropped and
recreated once (documented, with a deletion-protection escape hatch, in
`tables.py`).

---

## 5. What this design does *not* try to solve

- **Sub-batch incremental fact loading** — see §4.6. Acceptable at the
  current batch cadence; the fix if that changes is well understood and
  localized to one query.
- **Long-running jobs outliving the Cloud Function's timeout** — a 42M+
  67M-row full reprocess is a real risk against the 540s limit. The BigQuery
  job itself keeps running past a function timeout and `--retry` will pick
  it back up (everything here is idempotent), but the control-table row can
  read `FAILED` while the underlying data actually finished correctly. Worth
  watching, not yet fixed.
- **SCD2 history on `dim_product`** — the schema is explicitly SCD1
  (overwrite); this was validated against the data (well under 0.2% of
  products show a category/brand "change," and those are null-to-populated
  fill-ins, not real reassignments), so history tracking would add
  complexity with no real signal behind it.
