-- =============================================================================
-- View: vw_brand_purchases
--
-- Dashboard requirement: "Which brands generate the most purchases?"
--
-- Grain       : one row per brand (all-time).
-- Source      : fact_events, dim_brand.
-- revenue      = SUM(price) over purchase-event rows only. The Gold fact
--               table has no separate quantity/order-total column, so each
--               purchase event's price is the unit of revenue counted here
--               (checked against schemas.py before writing this - there is
--               no quantity field anywhere in Gold).
-- UNKNOWN brand (-1) is included like any other brand, not filtered out, so
--               its purchase volume stays visible rather than silently
--               disappearing from a "top brands" ranking.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_brand_purchases` AS
WITH agg AS (
  SELECT
    brand_key,
    SUM(is_purchase) AS purchase_count,
    SUM(IF(is_purchase = 1, price, 0)) AS revenue,
    COUNT(DISTINCT IF(is_purchase = 1, user_id, NULL)) AS unique_purchasing_users
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY brand_key
)
SELECT
  b.brand_key,
  b.brand,
  a.purchase_count,
  a.unique_purchasing_users,
  a.revenue,
  RANK() OVER (ORDER BY a.purchase_count DESC) AS purchase_rank
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand` b ON b.brand_key = a.brand_key;
