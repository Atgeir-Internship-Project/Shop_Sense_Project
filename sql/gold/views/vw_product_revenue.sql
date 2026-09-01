-- =============================================================================
-- View: vw_product_revenue
--
-- Dashboard requirement: "Top Products ... by Revenue" - which products
-- generate the most revenue.
--
-- Grain       : one row per product (all-time).
-- Source      : fact_events, dim_product, dim_category, dim_brand.
-- category / brand: taken from dim_product (the product's assigned category
--               and brand), the same convention as vw_product_conversion.
-- revenue      = SUM(price) over purchase-event rows only - the standard
--               project revenue measure (no quantity/order-total column
--               exists in the Gold schema).
--
-- NO minimum-volume floor (unlike vw_product_conversion's views >= 30 rule):
--   revenue is an ADDITIVE money measure, not a small-sample rate. A product
--   that made $2,000 from a single purchase genuinely earned that revenue and
--   belongs on the leaderboard. The 30-view floor exists only to stop noisy
--   high-RATE / low-volume products distorting a rate ranking - not relevant
--   to a revenue ranking. conversion_rate is carried as context only.
--
-- Ranking      : RANK() (ties share a position; the gap after a tie correctly
--               reflects how many products out-earned this one). Computed over
--               the revenue > 0 subset only, in a separate CTE, then LEFT
--               JOINed back - so zero-revenue products stay in the view with
--               revenue_rank = NULL and consume no rank numbers (the
--               qualifying sequence has no gaps from disqualified rows).
-- No fan-out  : fact is aggregated to product FIRST; dim_product /
--               dim_category / dim_brand are all one row per key, so the joins
--               are many-to-one and revenue cannot be multiplied.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_product_revenue` AS
WITH agg AS (
  SELECT
    product_key,
    SUM(is_view)                       AS views,
    SUM(is_cart)                       AS carts,
    SUM(is_purchase)                   AS purchases,
    SUM(IF(is_purchase = 1, price, 0)) AS revenue
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY product_key
),
ranked AS (
  SELECT
    product_key,
    RANK() OVER (ORDER BY revenue DESC) AS revenue_rank
  FROM agg
  WHERE revenue > 0
)
SELECT
  p.product_key,
  p.product_id,
  c.category_code,
  c.category_name,
  b.brand,
  a.views,
  a.carts,
  a.purchases,
  a.revenue,
  SAFE_DIVIDE(a.purchases, a.views) AS conversion_rate,
  r.revenue_rank
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_product`  p ON p.product_key  = a.product_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = p.category_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand`    b ON b.brand_key    = p.brand_key
LEFT JOIN ranked r ON r.product_key = a.product_key;
