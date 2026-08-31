-- =============================================================================
-- View: vw_category_cart_purchase_dropout
--
-- Dashboard requirement: "Which categories have the highest cart -> purchase
-- drop-off?"
--
-- Grain       : one row per (category, date)
-- Source      : fact_events, dim_category
-- Metric type : aggregate/macro conversion (event-count ratio), same
--               methodology as vw_category_view_cart_dropout - see that
--               file for the full rationale.
-- Denominator : carts (cart_to_purchase_rate = purchases / carts). A
--               category/day with carts but 0 purchases correctly shows
--               rate = 0, dropoff = 1. A category/day with 0 carts shows
--               NULL (undefined), not a false 0% or 100%.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_category_cart_purchase_dropout` AS
WITH agg AS (
  SELECT
    category_key,
    date_key,
    SUM(is_cart) AS carts,
    SUM(is_purchase) AS purchases
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY category_key, date_key
)
SELECT
  c.category_key,
  c.category_code,
  c.category_name,
  a.date_key,
  a.carts,
  a.purchases,
  SAFE_DIVIDE(a.purchases, a.carts) AS cart_to_purchase_rate,
  1 - SAFE_DIVIDE(a.purchases, a.carts) AS cart_to_purchase_dropoff
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c
  ON c.category_key = a.category_key;
