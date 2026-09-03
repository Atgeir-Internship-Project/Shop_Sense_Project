# ShopSense GenAI analyst — how it works and why

The conversational layer on top of the semantic layer. A business user opens
the ADK Web UI, asks a question in plain English, and gets an answer computed
from the real Gold data in BigQuery.

---

## 1. The concept

A **grounded analyst agent**: an LLM (Gemini, via Google ADK) that can only
answer by calling a small set of tools. It does not know any numbers - it
turns a question into a *structured request* against the semantic layer, runs
it on BigQuery, and reads back the rows.

Files: [`genai/shopsense_agent/`](../genai/shopsense_agent/).

The four tools:

| Tool | What it does |
|---|---|
| `get_semantic_catalog` | returns every metric / dimension / time-grain / segment name (from `semantic/metrics.yaml`) |
| `explain_metric` | returns one metric's formula + business meaning |
| `run_metric_query` | metric(s) × dimension(s) × filters × time-grain → runs it, returns rows |
| `run_segment_query` | a named population (`high_intent_never_purchase`) → runs it, returns rows |

---

## 2. Why it is built this way

**Why not let the LLM write SQL against `fact_events`?** It would pick the
wrong grain, invent joins, define "conversion" three ways in one chat, forget
the `UNKNOWN` bucket, and double-count on fan-out. The [semantic
layer](SEMANTIC_LAYER.md) already solved that: the agent picks *names*, a
deterministic builder writes the *SQL*.

**Why the "never state a number you didn't get from a tool" rule?** The single
worst failure for an analytics agent is a confident wrong number. The system
prompt forbids it, and every factual path goes through BigQuery.

**Why anchor "this week" on the data, not the clock?** The data is Oct–Nov
2019. `CURRENT_DATE` would return nothing. `last_n_days` is compiled as
`event_date >= DATE_SUB((SELECT MAX(event_date) FROM vw_semantic_events), …)`.

**Why the same semantic layer as the dashboard?** So the agent's "conversion
rate" and the Looker tile's "conversion rate" are the same number, by
construction (context doc §27–§28).

**Why tests with a fake runner?** The tool contract - name resolution,
request shaping, errors returned as data, forgiving input parsing - is
testable with no model, no ADK, no BigQuery. The LLM's judgement (does it pick
the right call?) is a separate, live eval driven by `eval/eval_questions.yaml`.

---

## 3. How it works

```
                 ADK Web UI  (adk web)
                       |
                       v
                 root_agent  (Gemini + INSTRUCTION)
                       |
        +--------------+-----------------------------+
        |              |                             |
        v              v                             v
 get_semantic_    explain_metric          run_metric_query /
   catalog                                run_segment_query
        |                                          |
        |                                 semantic_layer.build_*_query
        |                                          |
        |                            CompiledQuery { sql, parameters }
        |                                          |
        |                                 BigQueryRunner
        |                                   - dry run (validate)
        |                                   - execute (parameterised)
        |                                          |
        +---------------- rows / definitions ------+
                       |
                       v
        agent writes a concise NL answer, citing the
        metric definition when it matters
```

`bigquery_runner.py` is deliberately separate from `tools.py`: importing the
tools needs only the semantic layer, and tests inject a fake runner. The real
`google.cloud.bigquery` client is imported lazily on the first query.

---

## 4. Example

**User:** "Which category has the highest cart-to-purchase drop-off?"

1. Agent → `get_semantic_catalog()` → sees `cart_to_purchase_dropoff`, `category`.
2. Agent → `run_metric_query(metrics=["cart_to_purchase_dropoff", "carts", "purchases"], dimensions=["category"], order_by="cart_to_purchase_dropoff")`.
3. Builder →
   ```sql
   SELECT category_name AS category,
          1 - SAFE_DIVIDE(SUM(is_purchase), SUM(is_cart)) AS cart_to_purchase_dropoff,
          SUM(is_cart) AS carts, SUM(is_purchase) AS purchases
   FROM `...vw_semantic_events`
   GROUP BY 1 ORDER BY cart_to_purchase_dropoff DESC LIMIT 50
   ```
4. Runner dry-runs, then executes.
5. Agent: *"`electronics.telephone` has the highest cart→purchase drop-off at
   82.4% — 41,003 carts, 7,214 purchases."*

---

## 5. How it fits into ShopSense

```
 Gold star schema
        |
   vw_semantic_events                  (1 row / event, all dims joined)
        |
   semantic/  (metrics.yaml + builder)  <-- single source of truth
        |
   genai/shopsense_agent/  (ADK tools + agent)
        |
   adk web  ->  Business user
```

The agent adds no analytics logic of its own. It is a natural-language front
end to the same catalog the dashboard uses.

---

## 6. Status & roadmap

| Step | Status |
|---|---|
| Tools (`get_semantic_catalog`, `explain_metric`, `run_metric_query`, `run_segment_query`) | **done** |
| `BigQueryRunner` (dry-run + execute, param binding) | **done** |
| Agent + system instruction (`agent.py`, `prompts.py`) | **done** |
| Tool-contract tests (fake runner) | **done** — 15 tests |
| Eval question set + compilation test | **done** — `eval/eval_questions.yaml`, 14 questions |
| `pip install google-adk`, deploy `vw_semantic_events`, `adk web` smoke test | pending (needs GCP creds) |
| Live eval: run `eval_questions.yaml` through the model, score answers | pending |
| ADK Web UI deployment (Cloud Run) | pending |

### Not yet handled (add when needed)

- **Multi-turn "and by brand?"** — ADK keeps session state; the instruction
  tells the agent to re-query, not reuse a stale number. Verify in live eval.
- **Roll-ups below L1** — only `category` (exact level) and `category_l1`
  (top) are dimensions. A mid-tree roll-up would need another dimension driven
  by `bridge_category_hierarchy`.
- **Product-name questions** — `dim_product` has only `product_id`, no title.
