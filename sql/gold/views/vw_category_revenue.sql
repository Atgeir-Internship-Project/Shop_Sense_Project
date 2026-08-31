-- =============================================================================
-- View: vw_category_revenue
--
-- Dashboard requirement: "Which categories generate the most revenue?"
--
-- Grain       : one row per category (all-time).
-- Source      : fact_events, dim_category.
-- revenue      = SUM(price) over purchase-event rows only - same rationale
--               as vw_brand_purchases: no quantity/order-total column exists
--               anywhere in the Gold schema, so summing the purchase-event
--               price is the correct (and only available) revenue measure.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_category_revenue` AS
WITH agg AS (
  SELECT
    category_key,
    SUM(IF(is_purchase = 1, price, 0)) AS revenue,
    SUM(is_purchase) AS purchase_count,
    COUNT(DISTINCT IF(is_purchase = 1, user_id, NULL)) AS unique_purchasing_users
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY category_key
)
SELECT
  c.category_key,
  c.category_code,
  c.category_name,
  a.revenue,
  a.purchase_count,
  a.unique_purchasing_users,
  RANK() OVER (ORDER BY a.revenue DESC) AS revenue_rank
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = a.category_key;
