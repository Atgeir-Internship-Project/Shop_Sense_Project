# Gold-layer analytical views (Looker Studio dashboard layer)

Reusable BigQuery views on top of the existing Gold star schema
(`shopsense_analytics_gold`), built for the Looker Studio dashboard. They are
a read-only layer on top of Gold — nothing here modifies `fact_events` or any
`dim_*` table, and no new physical table is created. A future conversational
AI agent is **not** limited to these views; it can query the Gold schema
directly. These views exist purely to give the dashboard clean, pre-aggregated,
purpose-specific building blocks.

Files: [sql/gold/views/*.sql](../sql/gold/views/), one `CREATE OR REPLACE VIEW`
per file, deployed by [deploy_views.ps1](../sql/gold/views/deploy_views.ps1)
(auto-discovers every `vw_*.sql`, so a new file needs no script change).

The set is in two groups:

- **Views 1–12** — the original business-insight views, one per dashboard
  question.
- **Views 13–15** — the Overview / revenue set added for the executive
  dashboard (`vw_business_summary`, `vw_category_daily_summary`,
  `vw_product_revenue`). Adding them also extended three existing views —
  `vw_conversion_trend` (+`revenue`, +`avg_purchase_value`), `vw_category_revenue`
  (+`views`, +`carts`, +`conversion_rate`, +`revenue_share`) and
  `vw_brand_purchases` (+`views`, +`carts`, +`conversion_rate`, +`revenue_rank`) —
  rather than creating near-duplicate `vw_revenue_daily` / `vw_brand_revenue`
  views. All extensions are additive (new columns only); existing dashboard
  references keep working.

> **`vw_semantic_events` is also in this folder but is NOT a dashboard tile.**
> It is the wide, one-row-per-event base view that the semantic layer and the
> GenAI agent build queries against — see
> [SEMANTIC_LAYER.md](SEMANTIC_LAYER.md). It deploys through the same
> `deploy_views.ps1`. None of the cross-cutting rules below (pre-aggregated
> grain, percentile thresholds, etc.) apply to it.

## Cross-cutting decisions (apply to every view below)

- **Conversion type: aggregate/macro conversion** — `carts / views`,
  `purchases / carts` as event-count ratios at the category/product/brand
  grain. This is **not** a session-sequential funnel (tracking whether one
  specific view event was followed by a cart for the same visit) — the
  schema has no cart/order id linking a specific view to a specific later
  cart or purchase, so that kind of tracing isn't possible here. This is the
  standard definition used by most category/product-level funnel dashboards.
  `vw_high_intent_never_purchase` is the one exception — it is genuinely
  **user**-grain, per the dashboard requirement's own wording.
- **Category grain = the exact `category_code` level tagged on the event**,
  via a direct `category_key` join. None of these views roll a category up to
  its parent through `bridge_category_hierarchy` — a category and its
  sub-categories appear as separate rows. (The bridge table is still there if
  a future view needs a roll-up, e.g. the "Electronics vs Apparel" example in
  [validation_queries.sql](../cloud_functions/silver_to_gold/validation_queries.sql).)
- **UNKNOWN (`category_key`/`brand_key = -1`) rows are included**, labelled
  `'UNKNOWN'`, never filtered out silently. A Looker Studio filter can exclude
  them if a chart shouldn't show them.
- **Every rate uses `SAFE_DIVIDE`** — a zero denominator produces `NULL`
  (undefined), never a crash or a false `0%`/`100%`.
- **"High/low" thresholds are percentile-based** and the raw percentile is
  exposed as a column, so nothing is a hidden magic number.
- **Revenue = `SUM(price)` over purchase-event rows only.** There is no
  quantity or order-total column anywhere in the Gold schema (checked in
  `cloud_functions/silver_to_gold/schemas.py` before writing any revenue
  view), so one purchase event's `price` is the unit of revenue.
- **Performance:** every view aggregates `fact_events` down to its target
  grain in a CTE *before* joining to dimension tables, and any window
  function (`RANK`, `PERCENT_RANK`, `NTILE`) runs on that already-aggregated,
  small result — never on the raw fact table.
- **All-time vs date-grain (Overview set).** Two filtering modes:
  - *All-time snapshot* — `vw_business_summary`, `vw_category_revenue`,
    `vw_product_revenue`, `vw_brand_purchases`. Pre-aggregated, **not**
    date-filterable. Use for lifetime KPIs and leaderboards.
  - *Date-grain* — `vw_conversion_trend` (per day),
    `vw_category_daily_summary` (per day × category). Filter `date_key` in the
    BI tool for every trend / "in November" / "between X and Y" question.
    Additive columns (`views`, `carts`, `purchases`, `revenue`) `SUM` over any
    range; **rate columns are per-row and must be recomputed** from the summed
    components for a multi-day range.
- **Additive vs distinct-count metrics.** `views` / `carts` / `purchases` /
  `revenue` are additive. `COUNT(DISTINCT user_id / session_key)` is **not** —
  a period-level unique count must be computed once over the whole period
  (`vw_business_summary`), never by summing daily counts. `daily_active_users`
  / `daily_sessions` in `vw_conversion_trend` are daily-only: use `AVG`, never
  `SUM`.
- **`revenue` ranking uses no volume floor** — unlike the `views >= 30` rule
  for the *rate* ranking in `vw_product_conversion`. Revenue is real money at
  any view count; the floor only ever existed to keep noisy low-volume
  products off a *rate* leaderboard.

---

## View 1 — `vw_category_view_cart_dropout`
**Requirement:** Which categories have the highest view → cart drop-off?
**Grain:** category × date. **Source:** `fact_events`, `dim_category`.
**Metrics:** `views`, `carts`, `view_to_cart_rate = carts/views`,
`view_to_cart_dropoff = 1 - rate`.
**Chart:** bar chart of `view_to_cart_dropoff` by `category_code`, filterable
by `date_key`.

## View 2 — `vw_category_cart_purchase_dropout`
**Requirement:** Which categories have the highest cart → purchase drop-off?
**Grain:** category × date. **Source:** `fact_events`, `dim_category`.
**Metrics:** `carts`, `purchases`, `cart_to_purchase_rate`,
`cart_to_purchase_dropoff`.
**Chart:** bar chart of `cart_to_purchase_dropoff` by `category_code`.

## View 3 — `vw_high_intent_never_purchase`
**Requirement:** Who are the high-intent users who never purchase?
**Grain:** user (all-time roster). **Source:** `fact_events` only.
**Definition:** a user with ≥1 cart event and 0 purchase events — kept
identical to the definition already used and validated in
[validation_queries.sql](../cloud_functions/silver_to_gold/validation_queries.sql)
(Business Question 2), rather than inventing a second one.
`remove_from_cart` is not a signal here — it doesn't occur in this dataset
(confirmed during Silver profiling).
**Metrics:** `views`, `carts`, `purchases` (always 0 by definition),
`sessions`.
**Chart:** table, sorted by `carts` descending.

## View 4 — `vw_product_high_views_low_purchases`
**Requirement:** Which products have high views but low purchases?
**Grain:** product (all-time). **Source:** `fact_events`, `dim_product`,
`dim_category`, `dim_brand`.
**Thresholds:** `is_high_view_low_purchase = TRUE` when
`views_percentile >= 0.75` (top quartile of viewed products) **AND**
`conversion_percentile <= 0.50` (at/below median conversion). Both raw
percentiles are exposed so the cutoff is auditable.
**Chart:** table or scatter (`views` vs `conversion_rate`), filter on the flag.

## View 5 — `vw_product_conversion`
**Requirement:** Which products have the highest conversion rate?
**Grain:** product (all-time). **Source:** same as View 4.
**Minimum-volume rule:** `views >= 30` before a product is eligible for
`conversion_rank` (a standard small-sample-size floor — otherwise a product
with 1 view and 1 purchase would show a "100%" rate and outrank real
performers). Products below the floor still appear
(`qualifies_for_ranking = FALSE`, `conversion_rank = NULL`) — not dropped.
**Chart:** ranked bar/table of `conversion_rate`, filtered to
`qualifies_for_ranking = TRUE` for a "top products" chart.

## View 6 — `vw_brand_purchases`
**Requirement:** Which brands generate the most purchases? *(+ "top brands by
revenue" — this view covers both, so no separate `vw_brand_revenue` exists.)*
**Grain:** brand (all-time). **Source:** `fact_events`, `dim_brand`.
**Metrics:** `views`, `carts`, `purchase_count`, `unique_purchasing_users`,
`revenue`, `conversion_rate`, `purchase_rank`, `revenue_rank`. `UNKNOWN` brand
included.
**Two ranks:** `purchase_rank` (by event volume) and `revenue_rank` (by money)
can disagree — few expensive purchases vs many cheap ones — and that gap is
itself an insight.
**Chart:** ranked bar chart of `purchase_count` or `revenue` by `brand`.

## View 7 — `vw_category_revenue`
**Requirement:** Which categories generate the most revenue? *(+ "revenue by
category" — revenue share, conversion.)*
**Grain:** category (all-time). **Source:** `fact_events`, `dim_category`.
**Metrics:** `views`, `carts`, `purchase_count`, `revenue`,
`unique_purchasing_users`, `conversion_rate`, `revenue_share`, `revenue_rank`.
**`revenue_share`** = category revenue / **global all-time** revenue
(`SUM() OVER ()`). This view has no date dimension, so the denominator is
unambiguously the whole dataset. For a date-scoped share, use
`vw_category_daily_summary` and compute "% of total" in the BI tool.
**Chart:** ranked bar chart of `revenue` (or `revenue_share`) by `category_code`.

## View 8 — `vw_product_cart_abandonment`
**Requirement:** Which products have the highest cart abandonment?
**Grain:** product (all-time, `carts > 0` only). **Source:** `fact_events`,
`dim_product`, `dim_category`, `dim_brand`.
**Redefined metric (data gap):** no `remove_from_cart` event exists in this
dataset, so "abandoned" = a cart not accompanied by a purchase for that
product: `abandoned_cart_count = GREATEST(carts - purchases, 0)`,
`cart_abandonment_rate = 1 - purchases/carts`. This is an aggregate measure
(no cart/order id links one specific cart to one specific purchase), and is
mathematically the complement of View 2's cart→purchase rate at product
grain. `GREATEST(..., 0)` guards against "buy now" purchases that skip the
cart step, which would otherwise make `purchases > carts`.
**Chart:** ranked table/bar chart of `cart_abandonment_rate`.

## View 9 — NOT IMPLEMENTED: category remove-from-cart rate
**Requirement:** Which categories have the highest remove-from-cart rate?
**Status: blocked by the data.** `event_type` only ever takes `view`, `cart`,
`purchase` in this dataset — `remove_from_cart` does not occur (confirmed
during Silver profiling: `cloud_functions/staging_to_silver` only recognises
those three, per the original data-quality findings). There is nothing to
compute a "remove-from-cart rate" from. Building a view that always returns
`0` for every category would look like real data on a dashboard tile while
actually meaning "this event type doesn't exist" — that's misleading, so it
was not built.
**Recommendation:** drop this dashboard tile, or repoint it at View 2
(`vw_category_cart_purchase_dropout`), the closest real signal available. If
`remove_from_cart` events are ever added upstream (Bronze → Silver → Gold
would all need to carry an `is_remove_from_cart` flag first), this view can
be added the same way as the others.

## View 10 — `vw_conversion_trend`
**Requirement:** How does conversion change daily/weekly/monthly? *(+ "revenue
over time" — this view covers both, so no separate `vw_revenue_daily` exists.)*
**Grain:** one row per calendar day (via `dim_date`). **Source:**
`fact_events`, `dim_date`.
**Design:** `year`, `quarter`, `month`, `month_name`, `week`, `day_of_week`,
`is_weekend` all ride on the same row as the daily metrics, so Looker Studio
can group to daily, weekly, or monthly using its own date-grouping control on
**one** view — no need for three near-duplicate views.
**Metrics:** `views`, `carts`, `purchases`, `revenue`, `daily_active_users`,
`daily_sessions`, `view_to_cart_rate`, `cart_to_purchase_rate`,
`view_to_purchase_rate`, `avg_purchase_value`.
**Additive vs not:** `views`/`carts`/`purchases`/`revenue` sum over any date
range; the rate columns and `avg_purchase_value` must be recomputed from the
summed components for a range; `daily_active_users`/`daily_sessions` are
daily-only — `AVG` across days, never `SUM` (a weekly/monthly unique-user
count needs a finer grain or `vw_business_summary`).
**Chart:** line chart, date on the x-axis, `revenue` or a rate as the metric;
group-by set to day/week/month in Looker Studio.

## View 11 — `vw_price_conversion`
**Requirement:** Does product price affect conversion rate?
**Grain:** product (all-time, `views > 0` only). **Source:** `fact_events`,
`dim_product`, `dim_category`, `dim_brand`.
**`avg_price`:** `dim_product` deliberately has no price column (price can
vary event to event, e.g. a sale) — this view uses `AVG(price)` across a
product's own events as its one representative price.
**`price_quintile`:** `NTILE(5)` over the price distribution — a data-driven
5-way split, not fixed dollar cutoffs (no stated business reason existed for
specific breakpoints).
**Design choice:** returns product-level rows, not one correlation number —
per the requirement, Looker Studio should be able to explore the
price/conversion relationship itself (e.g. a scatter of `avg_price` vs
`conversion_rate`, or a bar of `conversion_rate` by `price_quintile`).

## View 12 — `vw_brand_engagement_conversion`
**Requirement:** Which brands have high engagement but low conversion?
**Grain:** brand (all-time, `engagement > 0` only). **Source:**
`fact_events`, `dim_brand`.
**`engagement`** = `views + carts` (no `remove_from_cart` signal available).
**Thresholds:** `is_high_engagement_low_conversion = TRUE` when
`engagement_percentile >= 0.75` **AND** `conversion_percentile <= 0.25`
(conversion = `purchases/engagement`). Both percentiles exposed.
**Chart:** scatter of `engagement` vs `conversion_rate` by brand, or a table
filtered to the flag.

---

# Overview & revenue views (executive dashboard)

Added for the "Show Overview" requirement. See the two extra cross-cutting
bullets above (*all-time vs date-grain*, *additive vs distinct-count*).

## View 13 — `vw_business_summary`
**Requirement:** "Show Overview" — the headline KPI strip.
**Grain:** **one row** — the entire `fact_events` dataset. Deliberate: the
distinct user / session counts can only be computed correctly by counting
`DISTINCT` once over the whole table, never by summing daily counts.
**Source:** `fact_events` only.
**Metrics:** `total_unique_users`, `total_unique_sessions`, `total_events`,
`total_views`, `total_carts`, `total_purchases`, `total_purchasing_users`,
`total_revenue`, `conversion_rate` (= purchases/views), `view_to_cart_rate`,
`cart_to_purchase_rate`, `avg_purchase_value` (= revenue/purchases, per
**event** — not AOV, no order grain exists), `avg_purchasing_session_value`
(AOV **proxy** — revenue / #sessions with ≥1 purchase), `revenue_per_user`
(ARPU), `revenue_per_purchasing_user`.
**Date filter:** none — pre-aggregated, not filterable. For date-range KPIs,
build the scorecards on `vw_conversion_trend` (sum additive columns, recompute
rates). Period-level unique users under a date filter is not supported here;
show it only on the all-time tile, or add a finer `(date_key, user_id)` view.
**Chart:** scorecard / KPI tiles.

## View 14 — `vw_category_daily_summary`
**Requirement:** "Funnel view by category" + "daily/weekly/monthly summary",
scoped to a selected date range and/or category.
**Grain:** one row per **(`date_key`, `category_key`)**. **Source:**
`fact_events`, `dim_category`, `dim_date`.
**Metrics:** `views`, `carts`, `purchases`, `revenue`, `conversion_rate`,
`view_to_cart_rate`, `cart_to_purchase_rate`, `avg_purchase_value`, plus
`year`/`month`/`month_name`/`week` for grouping.
**Consolidation:** superset of Views 1 & 2 (their `*_dropoff` columns are just
`1 - rate`) with `purchases` and `revenue` added. Views 1 & 2 can be retired
once the Overview tiles are repointed here.
**Date filter:** filter `date_key` and/or `category_*` in the BI tool.
Additive columns sum over any range; rates must be recomputed from the summed
components. No `revenue_share` column — the "% of total" denominator depends
on the selected range, so compute it in the BI tool.
**Chart:** line chart of `revenue` (or a rate) by `date_key`, filtered to one
category; or a category bar chart for a fixed date range.

## View 15 — `vw_product_revenue`
**Requirement:** "Top products by revenue."
**Grain:** product (all-time). **Source:** `fact_events`, `dim_product`,
`dim_category`, `dim_brand` (category/brand via `dim_product`, as in View 5).
**Metrics:** `views`, `carts`, `purchases`, `revenue`, `conversion_rate`
(context only), `revenue_rank`.
**No minimum-volume floor** (unlike View 5's `views >= 30`): revenue is an
additive money measure, real at any view count. `RANK()` runs over the
`revenue > 0` subset only, then `LEFT JOIN`ed back, so zero-revenue products
stay in the view with `revenue_rank = NULL` and leave no gaps in the
qualifying sequence.
**Date filter:** none (all-time). Date-scoped product revenue would need a
`(date_key, product_key)` view (~10M rows) — not built; add only on request.
**Chart:** ranked bar / table of `revenue`, optionally filtered by category or
brand.

---

## Requirement → View → Metrics → Chart

| # | Dashboard requirement | View | Key metrics | Recommended chart |
|---|---|---|---|---|
| 1 | Category view→cart drop-off | `vw_category_view_cart_dropout` | views, carts, view_to_cart_rate, dropoff | Bar chart |
| 2 | Category cart→purchase drop-off | `vw_category_cart_purchase_dropout` | carts, purchases, cart_to_purchase_rate, dropoff | Bar chart |
| 3 | High-intent users who never purchase | `vw_high_intent_never_purchase` | user_id, carts, purchases, sessions | Table |
| 4 | Products: high views, low purchases | `vw_product_high_views_low_purchases` | views, conversion_rate, is_high_view_low_purchase | Scatter / table |
| 5 | Products: highest conversion rate | `vw_product_conversion` | conversion_rate, conversion_rank | Ranked bar |
| 6 | Brands: most purchases / most revenue | `vw_brand_purchases` | purchase_count, revenue, purchase_rank, revenue_rank | Bar chart |
| 7 | Categories: most revenue / revenue share | `vw_category_revenue` | revenue, revenue_share, conversion_rate, revenue_rank | Bar chart |
| 8 | Products: highest cart abandonment | `vw_product_cart_abandonment` | cart_abandonment_rate, abandoned_cart_count | Ranked bar |
| 9 | Category remove-from-cart rate | *not implemented — blocked by data, see above* | — | — |
| 10 | Daily/weekly/monthly conversion + revenue | `vw_conversion_trend` | views/carts/purchases/revenue, rates, avg_purchase_value by day/week/month | Line chart |
| 11 | Price vs conversion | `vw_price_conversion` | avg_price, price_quintile, conversion_rate | Scatter / bar by quintile |
| 12 | Brands: high engagement, low conversion | `vw_brand_engagement_conversion` | engagement, conversion_rate, flag | Scatter |
| 13 | Overview KPI strip | `vw_business_summary` | total users/sessions/events/revenue, overall rates, avg_purchase_value, ARPU | Scorecard tiles |
| 14 | Category funnel + revenue over a date range | `vw_category_daily_summary` | views/carts/purchases/revenue + 3 rates per (date, category) | Line / bar chart |
| 15 | Top products by revenue | `vw_product_revenue` | revenue, revenue_rank, conversion_rate | Ranked bar / table |

---

## Deploying

```powershell
cd sql/gold/views
./deploy_views.ps1
```

Runs every `vw_*.sql` file through `bq query`. Idempotent — every file is
`CREATE OR REPLACE VIEW`, safe to re-run any time a definition changes.

## Validation checklist (run after every deploy)

This could not be executed from the environment these views were written in
(no BigQuery credentials available there, same limitation as the rest of this
project's development). Run each check and compare against the numbers
already validated in
[validation_queries.sql](../cloud_functions/silver_to_gold/validation_queries.sql):

1. **Compiles + returns rows** — `SELECT COUNT(*) FROM <view>` for all 15.
   `vw_business_summary` must return **exactly 1 row**.
2. **No accidental row multiplication** — for the product-grain views,
   `SELECT COUNT(*) FROM vw_product_conversion` should equal
   `SELECT COUNT(*) FROM dim_product` (one row per product, not per event).
   Same check for category-grain views against `dim_category`, and brand-grain
   views against `dim_brand`. For `vw_category_daily_summary`,
   `COUNT(*) = COUNT(DISTINCT (date_key, category_key))`.
3. **Cross-check totals against the fact table directly:**
   ```sql
   SELECT SUM(is_view) AS v, SUM(is_cart) AS c, SUM(is_purchase) AS p,
          SUM(IF(is_purchase = 1, price, 0)) AS revenue
   FROM `shop-sense-project.shopsense_analytics_gold.fact_events`;
   ```
   `SUM(views/carts/purchases)` from `vw_category_view_cart_dropout` /
   `vw_category_cart_purchase_dropout` / `vw_category_daily_summary` should
   match exactly. `SUM(revenue)` from `vw_category_revenue`,
   `vw_product_revenue`, `vw_brand_purchases`, `vw_conversion_trend` and
   `vw_category_daily_summary` should all equal the fact-table `revenue`
   above, and equal `total_revenue` in `vw_business_summary`.
4. **NULLs where expected, nowhere else** — rate columns should only be
   `NULL` when their denominator was 0; category/brand/product identifier
   columns should never be `NULL` (UNKNOWN rows carry the literal string
   `'UNKNOWN'`, not a `NULL`).
5. **Division-by-zero cases** — confirm a category/product/brand with 0 views
   (or 0 carts, or 0 engagement) shows a `NULL` rate, not an error or a
   fabricated 0%.
6. **Date coverage** — `MIN(date_key)`/`MAX(date_key)` in `vw_conversion_trend`
   and `vw_category_daily_summary` should match the range in `dim_date`, which
   in turn matches the min/max `event_time` in Silver.
7. **Manual spot-check** — pick one category and manually compute
   `view_to_cart_rate` with a plain `SELECT ... WHERE category_key = <x>`
   against `fact_events`, compare to the view's row for that category.
8. **`revenue_share` sums to 1** — `SELECT ROUND(SUM(revenue_share), 6) FROM
   vw_category_revenue` should be `1.0` (allow tiny float drift).
9. **Ranking has no gaps from disqualified rows** — in `vw_product_revenue`,
   `MAX(revenue_rank) <= COUNTIF(revenue > 0)`, and every `revenue > 0` row
   has a non-NULL `revenue_rank` (every `revenue = 0` row has `NULL`).
10. **Distinct counts are not additive** — `total_unique_users` in
    `vw_business_summary` must be **≤** the sum of daily
    `daily_active_users` from `vw_conversion_trend` (proof they are not the
    same number, i.e. nobody wired a `SUM`).

## Known limitations / assumptions

- View 9 is not implemented — see its section above.
- All conversion/drop-off metrics are aggregate (event-count) ratios, not
  session-sequential funnels — see "Cross-cutting decisions."
- Category views compare categories at whatever level they were tagged in
  the source data; they do not roll sub-categories up into their parent.
- Revenue assumes 1 purchase event = 1 unit (no quantity field exists in
  Gold to say otherwise).
- **True AOV (average order value) is not available** — there is no order /
  basket grain in the schema. `avg_purchase_value` is per purchase *event*;
  `avg_purchasing_session_value` (in `vw_business_summary`) is a proxy that
  treats "a session containing ≥1 purchase" as one order.
- **Date-scoped *product* revenue is not supported.** `vw_product_revenue` is
  all-time only. A "top products in November" question needs a
  `(date_key, product_key)` view (~10M rows) — add only if asked.
- **Period-level unique users under a date filter is approximate.**
  `vw_business_summary` gives the exact all-time figure; a date-filtered
  Overview should show unique users only when no date filter is applied, or
  run `COUNT(DISTINCT user_id)` against a finer `(date_key, user_id)` view.
- Percentile/quintile thresholds (Views 4, 5, 11, 12) are the specific
  values documented above and in each `.sql` file's header — they are a
  reasonable default, not a business-mandated rule; change them by editing
  the view and redeploying.
