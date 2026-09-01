-- =============================================================================
-- View: vw_category_daily_summary
--
-- Dashboard requirement: "Funnel View - view-cart-purchase by category" +
-- "Daily, weekly, monthly summary", scoped to a selected date range and/or
-- category (e.g. Electronics, 2019-11-01 -> 2019-11-30).
--
-- Grain       : one row per (date_key, category_key).
-- Source      : fact_events, dim_category, dim_date.
-- Category grain: fact_events.category_key = the category tagged ON THE EVENT
--               (via category_code), the same convention as vw_category_revenue
--               and the vw_category_*_dropout views. Not rolled up through
--               bridge_category_hierarchy - a category and its sub-categories
--               are separate rows.
-- Consolidates : this view is a superset of vw_category_view_cart_dropout and
--               vw_category_cart_purchase_dropout (their *_dropoff columns are
--               simply 1 - the matching rate). It also adds purchases and
--               revenue. Those two views can be retired in its favour once the
--               Overview tiles are repointed.
-- No fan-out  : fact is aggregated to (date, category) FIRST; dim_category is
--               1 row per category_key and dim_date is 1 row per date_key, so
--               both joins are many-to-one - revenue cannot be multiplied.
--
-- Date filter : filter date_key and/or category_name/category_code in the BI
--               tool. The additive columns (views/carts/purchases/revenue) SUM
--               correctly over any range; the rate columns are per-(day,
--               category) and MUST be recomputed from the summed components
--               for a multi-day range (SUM(purchases)/SUM(views), etc.).
-- Weekly/monthly: group by (year, month) or (year, week) from the dim_date
--               attributes carried on each row - never by month or week alone
--               (not unique across years).
-- revenue_share is deliberately NOT in this view: the "% of total" denominator
--               depends on the selected date range, which a view cannot know -
--               compute it in the BI tool. For an all-time category revenue
--               share, use vw_category_revenue.
-- Every rate uses SAFE_DIVIDE (NULL, never an error, on a zero denominator).
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_category_daily_summary` AS
WITH agg AS (
  SELECT
    date_key,
    category_key,
    SUM(is_view)                       AS views,
    SUM(is_cart)                       AS carts,
    SUM(is_purchase)                   AS purchases,
    SUM(IF(is_purchase = 1, price, 0)) AS revenue
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY date_key, category_key
)
SELECT
  a.date_key,
  d.year,
  d.month,
  d.month_name,
  d.week,
  c.category_key,
  c.category_code,
  c.category_name,
  a.views,
  a.carts,
  a.purchases,
  a.revenue,
  SAFE_DIVIDE(a.purchases, a.views)     AS conversion_rate,
  SAFE_DIVIDE(a.carts, a.views)         AS view_to_cart_rate,
  SAFE_DIVIDE(a.purchases, a.carts)     AS cart_to_purchase_rate,
  SAFE_DIVIDE(a.revenue, a.purchases)   AS avg_purchase_value
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c
  ON c.category_key = a.category_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_date` d
  ON d.date_key = a.date_key;
