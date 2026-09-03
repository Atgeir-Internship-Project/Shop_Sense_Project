# ShopSense Data Pipeline — how it works

A plain-English walkthrough of the medallion pipeline: what each piece does,
and why it is built the way it is.

---

## 1. The big picture

The pipeline is a **4-station assembly line**. A CSV of e-commerce events lands
in a Google Cloud Storage bucket, and it flows through four stations, getting
more refined at each one:

```
CSV lands in GCS  (bucket: shopsense-data-lake)
      |
      v   gcs_to_bronze          raw copy, no changes
BigQuery  shopsense_analytics.raw_data_table
      |
      v   bronze_to_staging      raw copy + batch tags
BigQuery  shopsense_analytics.shopsense_raw_stg
      |
      v   staging_to_silver      CLEAN + DE-DUPLICATE + NUMBER
BigQuery  shopsense_analytics_silver.transform_data_table
      |
      v   silver_to_gold         RESHAPE into a star schema for analytics
BigQuery  shopsense_analytics_gold.dim_* + fact_events
```

- Each **station is one Cloud Function** (Gen 2, Python).
- Between stations there is a **Pub/Sub topic**. When a station finishes it
  publishes a small "batch is ready" message; that message wakes up the next
  station. The stations never call each other directly.
- **The functions do not process the data themselves.** Each one writes a SQL
  command, hands it to BigQuery, waits for BigQuery to finish, and reads back a
  few summary numbers. BigQuery does all the work on the tens of millions of
  rows. This is why 42M rows go through in under a minute and the function never
  runs out of memory.

| Project | `shop-sense-project` | Region | `asia-south1` |
|---|---|---|---|
| Runtime identity | `shopsense-data-pipeline-sa` (one service account for all four functions) | | |

---

## 2. Station by station

### `gcs_to_bronze`
Trigger: a file is finalized in the `shopsense-data-lake` bucket.
It loads the CSV **exactly as-is** into `raw_data_table` (append only, nothing
cleaned), then publishes to **`shopsense-bronze-loaded`**.

### `bronze_to_staging`
Trigger: `shopsense-bronze-loaded`.
It loads the same CSV into `shopsense_raw_stg`, this time **stamping four
metadata columns onto every row**: `ingestion_timestamp`, `source_file_name`,
`batch_id`, `load_type` (`HISTORICAL` vs `INCREMENTAL`, from the folder the file
was uploaded to). `batch_id` is derived from the file's GCS generation, so it is
unique per upload and stable on retry. Progress is tracked in `ingestion_control`.
When done it publishes to **`shopsense-staging-loaded`**.

### `staging_to_silver`  *(built in this project)*
Trigger: `shopsense-staging-loaded`.
It reads only the rows for the one incoming `batch_id` and runs a single
BigQuery script that:

1. **Cleans every column** — trims spaces; lowercases `event_type`
   (`"VIEW "` -> `"view"`); turns blank text into real `NULL` for
   `category_code` / `brand` / `user_session`; parses the `event_time` text into
   a real `TIMESTAMP`; converts `price` to an exact `NUMERIC`.
2. **Quarantines bad rows** — it does not delete them, it *moves* them to
   `quarantine_data_table` with a reason: `PRICE_ZERO`, `SESSION_MISSING`,
   `INVALID_TIMESTAMP`.
3. **Removes exact duplicates** — see `row_hash` below. Surplus copies are
   quarantined as `EXACT_DUPLICATE`.
4. **Numbers the survivors** — see `surrogate_key` below.

The survivors are written to `transform_data_table`; the run is recorded in
`ingestion_transform_control` (`PROCESSING -> SUCCESS`, plus every count). When
done it publishes to **`shopsense-silver-loaded`**.

### `silver_to_gold`  *(built in this project)*
Trigger: `shopsense-silver-loaded`.
It reads the **whole** `transform_data_table` and builds a **star schema** in
`shopsense_analytics_gold`:

- **6 dimension / bridge tables** — rebuilt from scratch every run:
  `dim_date`, `dim_category`, `bridge_category_hierarchy`, `dim_brand`,
  `dim_product`, `dim_session`.
- **`fact_events`** — one row per event, holding number keys that point at the
  dimensions plus the measures (`price`, `is_view`, `is_cart`, `is_purchase`,
  `event_count`). Partitioned by `date_key`, clustered by the busiest keys.

The run is recorded in `ingestion_insight_control`, which also stores self-check
numbers (orphan keys, duplicate events, fact-vs-silver row count).

---

## 3. The key ideas, in plain terms

### `row_hash` (Silver)
The source data has **no ID column**. To find exact duplicates we build a
**fingerprint** of the 9 business columns (a SHA-256 of the cleaned values in a
fixed order). Two rows with the same fingerprint are identical — keep one copy,
quarantine the rest. Two rows that differ in any column get different
fingerprints and both stay.

### `surrogate_key` (Silver)
A plain counter — 1, 2, 3, … — assigned to each new Silver row. Because there is
no natural ID, this becomes the row's identity. It is computed as
`current maximum + row number`, so it **keeps counting across files** and never
restarts: the October load takes 1–42M, the first November file continues from
there.

### `FARM_FINGERPRINT` (Gold)
A BigQuery function that turns a text value like `"electronics.smartphone"` into
**the same integer every single time**. The Gold dimension keys
(`category_key`, `product_key`, `brand_key`, `session_key`) are all
`FARM_FINGERPRINT` of the business value. This is what lets us **wipe and rebuild
every dimension table on every run** without ever breaking the keys that
`fact_events` already stored — the key is a pure function of the value, so it
never changes.

### `MERGE` and idempotency
"Idempotent" = running the same batch twice does no harm.
- Each function first checks its control table: if the batch is already
  `SUCCESS`, it stops.
- `fact_events` uses `MERGE ... ON event_key WHEN NOT MATCHED THEN INSERT` —
  "add this event only if it is not already there". Re-run -> zero new rows.
- The Silver transform runs inside a transaction, so a failure rolls back
  cleanly with nothing half-written.

### Control tables
`ingestion_control`, `ingestion_transform_control`, `ingestion_insight_control` —
each has one row per batch that moves `PROCESSING -> SUCCESS` (or `FAILED`, which
a retry flips back to `PROCESSING`). They also store the run's numbers: rows in,
duplicates removed, rows written per table, and so on.

### Dimensions vs. fact
- **Dimensions** are the "nouns" — a product, a category, a day, a session.
  Small, descriptive, few rows.
- **The fact** is one row per event, carrying only number keys that point at the
  dimensions plus the numeric measures. Big, narrow, fast to aggregate.

### The bridge table
`category_code` is a **tree of varying depth**: `electronics` ->
`electronics.smartphone` (2 levels), `appliances.kitchen.oven` (3 levels).
`bridge_category_hierarchy` is a pre-computed list of every
ancestor -> descendant pair. A query can then ask "everything under
`electronics`" and roll up all sub-categories in one join — no fragile text
matching on the code.

---

## 4. Why it is built this way

- **All heavy work runs inside BigQuery.** The data is 42–67M rows per file;
  pulling that into a Cloud Function would be impossible. The function is only an
  orchestrator: build SQL, submit, wait, read a summary row.
- **Dimensions use rebuild + hash keys.** Because every key is a deterministic
  hash of a business value, the dimension tables can be dropped and rebuilt on
  every run with zero coordination, and they can never accumulate duplicates
  (there is no "append").
- **Only `fact_events` uses `MERGE`.** It is the one table that grows by
  appending new events, so it is the one place a re-run could double-insert —
  hence the `event_key` MERGE guard.
- **Nothing is silently discarded.** Bad rows are preserved in the quarantine
  table with a reason, so a decision can always be reviewed.

---

## 5. Infrastructure glue

Beyond the transform logic, the pipeline needs some GCP plumbing, most of which
the `deploy.ps1` scripts now handle automatically:

- **Pub/Sub topics** are created by the deploy scripts (they are not created by
  the `--trigger-topic` flag).
- The service account needs **`roles/pubsub.publisher`** on the topic it
  publishes to, and **`roles/run.invoker` + `roles/eventarc.eventReceiver`** so
  the trigger is allowed to invoke the function.
- Terraform creates the BigQuery tables **without column definitions**.
  `CREATE TABLE IF NOT EXISTS` will not retrofit a schema onto an existing empty
  table, so `staging_to_silver` and `silver_to_gold` attach the schema through
  the BigQuery client on first run (`tables.py` in each function).

---

## 6. Validating the Gold layer

Run the blocks in
[`cloud_functions/silver_to_gold/validation_queries.sql`](../cloud_functions/silver_to_gold/validation_queries.sql)
one at a time (BigQuery console or `bq query`):

| Check | Passes if |
|---|---|
| Run status (control table) | latest row `status = SUCCESS`, `fk_resolution_failures = 0`, `duplicate_event_keys = 0` |
| Row count | `fact_events` count **==** `transform_data_table` count |
| No duplicate events | `COUNT(*) == COUNT(DISTINCT event_key)` |
| No orphan foreign keys | every `*_key` in `fact_events` resolves to a dimension row |
| Dimension sizes | `dim_category` ~159, `dim_product` ~165K |
| Business questions | the three example queries return plausible, non-empty results |
