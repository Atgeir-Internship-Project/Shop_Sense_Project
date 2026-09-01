-- =============================================================================
-- View: vw_brand_purchases
--
-- Dashboard requirement: "Which brands generate the most purchases?" +
-- "Top ... Brands by Revenue" (brand revenue leaderboard).
--
-- Grain       : one row per brand (all-time).
-- Source      : fact_events, dim_brand.
-- revenue      = SUM(price) over purchase-event rows only. The Gold fact table
--               has no quantity/order-total column, so each purchase event's
--               price is the unit of revenue.
-- EXTENDED    : views, carts, conversion_rate and revenue_rank were added.
--               This makes a separate vw_brand_revenue unnecessary - the brand
--               revenue leaderboard is `ORDER BY revenue_rank` on this view.
-- Two ranks   : purchase_rank ranks by purchase_count (event volume),
--               revenue_rank ranks by revenue (money). They can disagree - a
--               brand with many cheap purchases vs a brand with few expensive
--               ones - and that disagreement is itself an insight.
-- UNKNOWN brand (brand_key = -1) is included like any other brand, not
--               filtered out, so its volume stays visible in a ranking.
-- No fan-out  : fact is aggregated to brand FIRST; dim_brand is one row per
--               brand_key, so the join is many-to-one.
-- conversion_rate uses SAFE_DIVIDE (NULL, never an error, when views = 0).
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_brand_purchases` AS
WITH agg AS (
  SELECT
    brand_key,
    SUM(is_view)                                       AS views,
    SUM(is_cart)                                       AS carts,
    SUM(is_purchase)                                   AS purchase_count,
    SUM(IF(is_purchase = 1, price, 0))                 AS revenue,
    COUNT(DISTINCT IF(is_purchase = 1, user_id, NULL)) AS unique_purchasing_users
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY brand_key
)
SELECT
  b.brand_key,
  b.brand,
  a.views,
  a.carts,
  a.purchase_count,
  a.unique_purchasing_users,
  a.revenue,
  SAFE_DIVIDE(a.purchase_count, a.views)       AS conversion_rate,
  RANK() OVER (ORDER BY a.purchase_count DESC) AS purchase_rank,
  RANK() OVER (ORDER BY a.revenue DESC)        AS revenue_rank
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand` b ON b.brand_key = a.brand_key;
