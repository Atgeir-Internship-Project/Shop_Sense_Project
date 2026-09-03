# ShopSense analyst agent

A Google ADK agent that answers natural-language questions about the ShopSense
e-commerce data by querying the semantic layer - never by guessing numbers.

```
genai/
  shopsense_agent/
    agent.py            root_agent (adk web discovers this)
    tools.py            get_semantic_catalog / explain_metric /
                        run_metric_query / run_segment_query
    bigquery_runner.py  executes a compiled query (dry-run then run)
    prompts.py          the system instruction
  eval/eval_questions.yaml   canonical Q -> expected tool call
  tests/                     tool contract + eval-question compilation
```

## How it answers a question

```
question -> get_semantic_catalog (once)  -> pick metric/dimension/filter names
         -> run_metric_query / run_segment_query
              -> semantic_layer.build_*_query   (deterministic, parameterised SQL)
              -> BigQueryRunner: dry-run to validate, then execute
         -> read rows -> concise NL answer
```

The model never emits SQL and can only reference names in
`../semantic/metrics.yaml`. Filter values are bound as query parameters.

## Run it locally

```powershell
# 1. deps
pip install -r requirements.txt

# 2. config - copy and fill in
copy .env.example .env
#   GOOGLE_GENAI_USE_VERTEXAI=TRUE + GOOGLE_CLOUD_PROJECT=shop-sense-project
#   (or GOOGLE_API_KEY for AI Studio)

# 3. auth for BigQuery (the tools query it)
gcloud auth application-default login

# 4. the Gold semantic view must be deployed
#    (sql/gold/views/deploy_views.ps1 - includes vw_semantic_events)

# 5. launch the ADK dev UI from the genai/ directory
cd ..
adk web
#   -> open the printed URL, pick "shopsense_agent", start chatting
```

Try: *"Which categories have the biggest view-to-cart drop-off this week?"*,
*"How much revenue did Electronics make in November?"*,
*"Who are the high-intent users who never purchased?"*

## Tests

```powershell
pip install -r tests/requirements-dev.txt   # just pytest + pyyaml
python -m pytest genai/tests/ -q            # from the repo root
```

These use a fake query runner - no google-adk, no BigQuery, no model needed.
They check name resolution, request shaping, error-as-data, and that every
question in `eval/eval_questions.yaml` compiles.

## Config (env)

| var | default | purpose |
|---|---|---|
| `SHOPSENSE_AGENT_MODEL` | `gemini-2.5-flash` | Gemini model for the agent |
| `SHOPSENSE_BQ_PROJECT` | `shop-sense-project` | BigQuery project the tools query |
| `SHOPSENSE_BQ_LOCATION` | `asia-south1` | BigQuery location |
| `GOOGLE_GENAI_USE_VERTEXAI` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_API_KEY` | - | Gemini auth (ADK standard) |
