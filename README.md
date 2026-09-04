# ShopSense

**An AI-powered e-commerce analytics platform.** Raw clickstream CSVs land in
Google Cloud Storage, flow through a medallion pipeline into a BigQuery star
schema, and are answered in plain English by a Gemini analyst that is grounded
on a governed metric catalog — so it queries the warehouse for every number and
never guesses.


---

## Table of contents

1. [What it does](#1-what-it-does)
2. [Architecture](#2-architecture)
3. [Repository layout](#3-repository-layout)
4. [The dataset](#4-the-dataset)
5. [Layer 1 — the medallion pipeline](#5-layer-1--the-medallion-pipeline)
6. [Layer 2 — the Gold star schema](#6-layer-2--the-gold-star-schema)
7. [Layer 3 — the analytical views](#7-layer-3--the-analytical-views)
8. [Layer 4 — the semantic layer](#8-layer-4--the-semantic-layer)
9. [Layer 5 — the GenAI analyst](#9-layer-5--the-genai-analyst)
10. [Layer 6 — the chat UI](#10-layer-6--the-chat-ui)
11. [Running it locally](#11-running-it-locally)
12. [Deploying to Cloud Run](#12-deploying-to-cloud-run)
13. [Infrastructure (Terraform)](#13-infrastructure-terraform)


---

## 1. What it does

Business users want answers to questions like:

- *Which categories have the highest view → cart drop-off this week?*
- *Who are our high-intent users who never purchase?*
- *What is the conversion funnel for Electronics vs Apparel?*
- *Which brands generate the most revenue?*

Writing SQL for each of these by hand doesn't scale, and pointing an LLM at raw
tables produces confident wrong answers. ShopSense solves this with two halves:

| Half | What it is |
|---|---|
| **Data platform** | A GCP-native, event-driven medallion pipeline (Bronze → Silver → Gold) that turns ~109M raw events into a clean BigQuery star schema, plus 16 reusable analytical views and a single metric catalog. |
| **Conversational analyst** | A Google ADK agent (Gemini) that maps a natural-language question to **names from the catalog**, lets a deterministic builder write the SQL, runs it against Gold, and explains the result. It cannot invent a number, a join, or a metric formula. |

Everything runs on Google Cloud: **Cloud Storage · Pub/Sub · Cloud Functions ·
BigQuery · Vertex AI · Cloud Run**, provisioned with **Terraform**.

**Project / region:** `shop-sense-project` · `asia-south1` (Vertex Gemini uses
the `global` endpoint).

---

## 2. Architecture

```
 CSV file  ──▶  Cloud Storage bucket  (shopsense-data-lake)
                        │  object-finalized event
                        ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │  MEDALLION PIPELINE  — 4 Cloud Functions, Pub/Sub between each        │
 │                                                                      │
 │  gcs_to_bronze      raw copy, no changes        → raw_data_table      │
 │       │ Pub/Sub  shopsense-bronze-loaded                              │
 │  bronze_to_staging  + batch_id, load_type, lineage → shopsense_raw_stg│
 │       │ Pub/Sub  shopsense-staging-loaded                             │
 │  staging_to_silver  clean · quarantine · de-dup · number             │
 │       │                                        → transform_data_table │
 │       │ Pub/Sub  shopsense-silver-loaded                              │
 │  silver_to_gold     build the star schema                            │
 │                     dim_date · dim_category · bridge_category_hierarchy│
 │                     dim_brand · dim_product · dim_session · fact_events│
 └──────────────────────────────────────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────────────────────┐
        ▼                                               ▼
 1 analytical views  (vw_*)                    vw_semantic_events
 (pre-aggregated, one per question)             (1 row / event, all dims joined)
        │                                               │
 Looker Studio dashboard                         semantic/metrics.yaml  (the catalog)
                                                        │
                                        genai/shopsense_agent  (ADK + Gemini)
                                                        │
                                        frontend/  (Streamlit chat UI)
                                                        │
                                                 Cloud Run  ──▶  public HTTPS URL
```

The functions never call each other — each publishes a "batch ready" Pub/Sub
message that wakes the next. None of them process row-level data in Python: each
one builds a SQL command, submits it to BigQuery, waits, and reads back a
summary row. That's why 42M–67M-row files move through in under a minute.



---

## 3. Repository layout

```
Shop_Sense_Project/
├── cloud_functions/              the 4 pipeline stations (Cloud Functions, Gen 2, Python)
│   ├── bronze/            CSV → raw_data_table
│   ├── staging/        + batch/lineage metadata → shopsense_raw_stg
│   ├── silver/        clean, quarantine, de-duplicate, surrogate keys
│   │   └── silver_sql.py         the Silver transform SQL
│   └── gold/           build the Gold star schema
│       ├── gold_sql.py           the 8-step BigQuery build script
│       ├── schemas.py            Gold table schemas (owned in code, not Terraform)
│       └── validation_queries.sql
│
├── sql/gold/views/              1 CREATE OR REPLACE VIEW files + deploy_views.ps1
│   ├── vw_semantic_events.sql   the wide base view the agent/semantic layer query
│   ├── vw_dashboard_overview.sql the single source for the Looker "Business Overview" page
│   └── vw_*.sql                  one per dashboard question
│
├── semantic/                    the metric catalog + deterministic SQL builder
│   ├── metrics.yaml             15 metrics, dimensions, time-grains, segments — one definition each
│   ├── semantic_layer.py        build_aggregate_query() / build_segment_query() → CompiledQuery
│   └── run_query.py            
│
├── genai/
│   ├── shopsense_agent/         the Google ADK agent
│   │   ├── agent.py             root_agent — Gemini + instruction + 4 tools
│   │   ├── prompts.py           the system instruction (never guess a number)
│   │   ├── tools.py             get_semantic_catalog / explain_metric / run_metric_query / run_segment_query
│   │   └── bigquery_runner.py   dry-run to validate, then execute with bound parameters
│   └── eval/eval_questions.yaml 14 canonical questions + their expected tool calls
│
├── frontend/                    the Streamlit chat UI
│   ├── app.py                   entrypoint  (streamlit run app.py)
│   ├── config/settings.py       loads frontend/.env, product constants, logging
│   ├── services/
│   │   ├── adk_service.py       THE integration point — drives root_agent via an ADK Runner
│   │   └── session_service.py   in-browser conversation bookkeeping (no database)
│   └── ui/                      chat.py · sidebar.py · styles.py · welcome.py
│
├── Terraform/                   GCS bucket, pipeline service account, BigQuery datasets
├── docs/                        6 deep-dive documents (see §15)
├── notebooks/profile.ipynb      source-data profiling
│
├── Dockerfile · .dockerignore · .gcloudignore · requirements.txt · .streamlit/
│                                Cloud Run packaging for the chat UI + in-process agent
└── README.md                    this file
```

Placeholder / historical: `src/`, `dashboard/`, `data/`,
scaffolding files are empty stubs; `sql/pr.py` is a superseded single-file
prototype of `bronze_to_staging` (the maintained version is the modular package).

---

## 4. The dataset

The public **REES46 "eCommerce behavior data from a multi-category store"**
dataset — monthly CSVs, one row per user event.

| Column | Notes |
|---|---|
| `event_time`, `event_type`, `user_id`, `user_session` | `event_type` ∈ `view`, `cart`, `purchase` |
| `product_id`, `category_id`, `category_code`, `brand` | `category_code` is a variable-depth dotted path (`electronics.audio.headphone`) |
| `price` | per-event price; no quantity or order-total column anywhere |

**Delivered scope:** **2019-October and 2019-November only** — ~42M + ~67M ≈
**109M events**. The dataset has **no `remove_from_cart` event** and no
cart/order identifier. Consequences that are deliberate, not gaps:

- Revenue = `SUM(price)` over purchase events (1 purchase event = 1 unit).
- Conversion is an **aggregate event-count ratio** (`carts / views`), not a
  session-sequential funnel — `cart → purchase` can legitimately exceed 100%.
- "This week" means the last 7 days *present in the data* (late Nov 2019).

---

## 5. Layer 1 — the medallion pipeline

Four **Gen 2 Cloud Functions**, each triggered by a Pub/Sub message from the
one before it. One service account (`shopsense-data-pipeline-sa`) runs all four.

| Function | Reads | Writes | Job |
|---|---|---|---|
| `gcs_to_bronze` | the CSV in GCS | `shopsense_analytics.raw_data_table` | exact raw copy, append only |
| `bronze_to_staging` | `raw_data_table` | `shopsense_raw_stg` | stamps `ingestion_timestamp`, `source_file_name`, `batch_id`, `load_type` (HISTORICAL / INCREMENTAL) on every row |
| `staging_to_silver` | rows for one `batch_id` | `shopsense_analytics_silver.transform_data_table` | trim / type-cast / null-normalise; **quarantine** bad rows (`PRICE_ZERO`, `SESSION_MISSING`, `INVALID_TIMESTAMP`, `EXACT_DUPLICATE`); collapse exact duplicates via a `row_hash` (SHA-256 of the 9 business columns); assign a running `surrogate_key` |
| `silver_to_gold` | the **whole** `transform_data_table` | `shopsense_analytics_gold.*` | rebuild the star schema (below) |

**Idempotency at every hop:** each function checks its control table (batch
already `SUCCESS` → stop); Silver runs inside a transaction; Gold uses `CREATE
OR REPLACE` for dimensions and a `MERGE` for the fact. Re-running a batch does
no harm.

**Control tables** — one row per batch, `PROCESSING → SUCCESS / FAILED`, plus
every run metric: `ingestion_control`, `ingestion_transform_control`,
`ingestion_insight_control`. Bad rows are preserved in `quarantine_data_table`
with a reason, never deleted.

---

## 6. Layer 2 — the Gold star schema

`silver_to_gold` submits **one BigQuery script** (`gold_sql.py`) that builds the
schema in dependency order:

| # | Table | Grain / build |
|---|---|---|
| 1 | `dim_date` | one row per calendar day, from the Silver date range |
| 2 | `dim_category` | every distinct `category_code` **exploded into its prefix levels** (`a.b.c` → `a`, `a.b`, `a.b.c`); key = `FARM_FINGERPRINT(path)`; + `UNKNOWN` (`-1`) |
| 3 | `bridge_category_hierarchy` | recursive closure over `dim_category` — every ancestor→descendant pair |
| 4 | `dim_brand` | one row per brand + `UNKNOWN` (`-1`) |
| 5 | `dim_product` | one row per `product_id` (SCD-1), consolidating a non-null category/brand from anywhere in the product's events |
| 6 | `dim_session` | one row per `user_session` — start/end time, event count, `has_purchase`, `is_multi_user` |
| 7 | `fact_events` | **one row per event**; `MERGE ON event_key`; measures `price` + `is_view` / `is_cart` / `is_purchase` (1/0); partitioned by `date_key`, clustered by `category_key, product_key, session_key` |
| 8 | metrics `SELECT` | row counts + FK-orphan check + duplicate-key check, one row |

:

- **`FARM_FINGERPRINT` hash keys** — a pure function of the business value, so
  every dimension can be dropped and rebuilt on every run without breaking a
  single key already stored on `fact_events`.
- **`MERGE` only on `fact_events`** — the one table that grows by appending; the
  one place a retry could double-insert.
- **`dim_category` keyed on `category_code`, not `category_id`** — profiling
  found up to 23 `category_id`s mapping to one `category_code`.
- **`UNKNOWN` members** — a NULL category/brand maps to a real `-1` row; a fact
  row is never lost to a join (`fk_resolution_failures = 0` is a checked
  invariant).

---

## 7. Layer 3 — the analytical views

16 `CREATE OR REPLACE VIEW` files in [`sql/gold/views/`](sql/gold/views/),
deployed together by `deploy_views.ps1`.


---

## 8. Layer 4 — the semantic layer

The single definition of every business metric, shared by the dashboard and the
agent so both return the same number.

  **dimensions** with synonyms (`department` → `category_l1`), 4 **time grains**
  (`day` / `week` / `month` / `quarter`), and 1 **segment**
  (`high_intent_never_purchase`, a `HAVING`-clause population).
- **[`semantic/semantic_layer.py`](semantic/semantic_layer.py)** —
  `SemanticLayer.load().build_aggregate_query(metrics, dimensions, filters,
  time_grain, order_by, limit)` → a `CompiledQuery(sql, parameters)`.
  - Only names in the catalog reach the SQL — an unknown metric raises.
  - Every filter value is a BigQuery `@pN` parameter — a question cannot inject
    SQL.
  - `last_n_days` anchors on `MAX(event_date)` in the data, never `CURRENT_DATE`.
- **[`semantic/run_query.py`](semantic/run_query.py)** — a CLI to compile a
  request and run it against BigQuery, for validation / debugging.


---

## 9. Layer 5 — the GenAI analyst

Built on **Google ADK** (Agent Development Kit). Model **`gemini-3.5-flash-lite`**
via **Vertex AI**.

**The four tools** ([`genai/shopsense_agent/tools.py`](genai/shopsense_agent/tools.py)) —
plain functions ADK wraps automatically:

| Tool | Does |
|---|---|
| `get_semantic_catalog` | returns every metric / dimension / segment name (also baked into the prompt, so it's rarely called) |
| `explain_metric` | one metric's formula + meaning |
| `run_metric_query` | takes metric / dimension / filter **names** → semantic layer compiles the SQL → runs it → `{sql, rows, row_count}` or `{error}` |
| `run_segment_query` | same, for a named `HAVING` population |

---

## 10. Layer 6 — the chat UI

A **Streamlit** app in [`frontend/`](frontend/).

- **[`app.py`](frontend/app.py)** — wiring only: init session state, draw the
  sidebar, show the welcome screen or the active conversation, route every
  input through one `_send` handler.
- **[`services/adk_service.py`](frontend/services/adk_service.py)** — **the only
  integration point**. `send_message(question, session_id, user_id)` drives
  `root_agent` through an ADK `Runner` + `InMemorySessionService` (built once
  per process with `@st.cache_resource`), reads the event stream (final text →
  answer, tool result → `sql` / `rows`), and lightly cleans the answer (strips
  backtick column names and `$` signs). Follow-up context ("its conversion
  rate", "why?") comes free from reusing the same ADK `session_id`.
- **[`services/session_service.py`](frontend/services/session_service.py)** —
  `Conversation` / `Message` dataclasses. Conversations live **only in
  `st.session_state`** (this browser tab) — new chat, rename, delete, clear,
  recent list. No database.
- **[`ui/`](frontend/ui/)** — `chat.py` (bubbles, collapsible SQL viewer, KPI /
  table, keyword-matched follow-up chips, loading), `sidebar.py` (brand header,
  + New Chat, Recent Chats, Settings), `styles.py`, `welcome.py`.

The UI never executes SQL — it only displays what the trusted backend returns.

---

## 11. Running it locally

### Prerequisites
- Python 3.12+ · a GCP project with the Gold layer already built in BigQuery
- `gcloud auth application-default login` (used for both Vertex Gemini and BigQuery)

### The agent (ADK dev UI)
```bash
pip install -r genai/shopsense_agent/requirements.txt
cd genai/shopsense_agent && cp .env.example .env   # fill in GOOGLE_CLOUD_PROJECT
cd .. && adk web                                    # http://localhost:8000
```

### The chat UI
```bash
pip install -r frontend/requirements.txt
cd frontend && cp .env.example .env                 # fill in your project id
streamlit run app.py                                # http://localhost:8501
```

### The Gold views
```powershell
cd sql/gold/views
./deploy_views.ps1        # runs every vw_*.sql through `bq query`
```

### An ad-hoc semantic-layer query
```bash
python semantic/run_query.py --metrics revenue,conversion_rate --dimensions category --limit 10
```

---

## 12. Deploying to Cloud Run

The [`Dockerfile`](Dockerfile) packages the Streamlit UI **plus the in-process
ADK agent** (one container, `SHOPSENSE_BACKEND=inprocess`). Auth is
**Application Default Credentials from the Cloud Run service account** — no key
file, no Secret Manager.

```powershell
gcloud config set project shop-sense-project

# service account must be able to reach Vertex + BigQuery, and you must be able
# to deploy "as" it:
gcloud iam service-accounts add-iam-policy-binding `
  shopsense-data-pipeline-sa@shop-sense-project.iam.gserviceaccount.com `
  --member="user:YOU@example.com" --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding shop-sense-project `
  --member="serviceAccount:shopsense-data-pipeline-sa@shop-sense-project.iam.gserviceaccount.com" `
  --role="roles/aiplatform.user"

# build (Cloud Build, no local Docker needed) + deploy
gcloud run deploy shopsense-chatbot `
  --source . --region=asia-south1 `
  --service-account=shopsense-data-pipeline-sa@shop-sense-project.iam.gserviceaccount.com `
  --allow-unauthenticated --session-affinity --cpu-boost `
  --cpu=1 --memory=1Gi --min-instances=0 --max-instances=3 --concurrency=8 --timeout=300 `
  --set-env-vars="SHOPSENSE_BACKEND=inprocess,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=shop-sense-project,GOOGLE_CLOUD_LOCATION=global,SHOPSENSE_AGENT_MODEL=gemini-3.5-flash-lite,SHOPSENSE_BQ_PROJECT=shop-sense-project,SHOPSENSE_BQ_LOCATION=asia-south1"
```

The command prints a public `https://…run.app` URL. Redeploy after a code
change with the same command (`gcloud run deploy … --source .`).

---

## 13. Infrastructure (Terraform)

[`Terraform/`](Terraform/) provisions the GCP resources the pipeline needs, as
reusable modules:

| Module | Creates |
|---|---|
| `storage` | the `shopsense-data-lake` landing bucket |
| `service_account` | `shopsense-data-pipeline-sa` (one identity for all four functions) |
| `bigquery` | the `shopsense_analytics` dataset (Bronze / Staging) |

Table **schemas** are intentionally *not* in Terraform — they live in each
function's `schemas.py` so they're versioned alongside the transform logic that
depends on them (see [docs/GOLD_LAYER_DESIGN.md §4.9](docs/GOLD_LAYER_DESIGN.md)).
Pub/Sub topics and the function triggers are created by each function's
`deploy.ps1`.

```bash
cd Terraform && terraform init && terraform plan && terraform apply
```