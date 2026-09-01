-- =============================================================================
-- View: vw_category_revenue
--
-- Dashboard requirement: "Which categories generate the most revenue?" +
-- "Revenue by Category" (revenue, revenue share, conversion).
--
-- Grain       : one row per category (all-time).
-- Source      : fact_events, dim_category.
-- Category grain: fact_events.category_key = the category tagged ON THE EVENT
--               (via category_code). Not rolled up through the bridge table.
-- revenue      = SUM(price) over purchase-event rows only - no quantity/
--               order-total column exists anywhere in the Gold schema, so the
--               purchase-event price is the correct (and only) revenue measure.
-- EXTENDED    : views, carts, conversion_rate and revenue_share were added.
--               revenue and revenue_rank keep their original definitions.
-- revenue_share = category revenue / GLOBAL all-time revenue (SUM OVER ()).
--               This view has no date dimension, so the denominator is
--               unambiguously the whole dataset. For a date-scoped revenue
--               share, use vw_category_daily_summary and compute "% of total"
--               in the BI tool - a view cannot know the selected date range.
-- Date filter : NONE (all-time aggregate). Use vw_category_daily_summary for
--               any date-scoped category question.
-- No fan-out  : fact is aggregated to category FIRST; dim_category is one row
--               per category_key, so the join is many-to-one.
-- Every rate uses SAFE_DIVIDE (NULL, never an error, on a zero denominator).
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_category_revenue` AS
WITH agg AS (
  SELECT
    category_key,
    SUM(is_view)                                       AS views,
    SUM(is_cart)                                       AS carts,
    SUM(is_purchase)                                   AS purchase_count,
    SUM(IF(is_purchase = 1, price, 0))                 AS revenue,
    COUNT(DISTINCT IF(is_purchase = 1, user_id, NULL)) AS unique_purchasing_users
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY category_key
)
SELECT
  c.category_key,
  c.category_code,
  c.category_name,
  a.views,
  a.carts,
  a.purchase_count,
  a.revenue,
  a.unique_purchasing_users,
  SAFE_DIVIDE(a.purchase_count, a.views)         AS conversion_rate,
  SAFE_DIVIDE(a.revenue, SUM(a.revenue) OVER ()) AS revenue_share,
  RANK() OVER (ORDER BY a.revenue DESC)          AS revenue_rank
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = a.category_key;
