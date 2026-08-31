-- =============================================================================
-- View: vw_product_high_views_low_purchases
--
-- Dashboard requirement: "Which products have high views but low purchases?"
--
-- Grain       : one row per product_id (all-time).
-- Source      : fact_events, dim_product, dim_category, dim_brand.
-- Threshold definition (percentile-based, not an arbitrary fixed number):
--   high_views    -> views_percentile >= 0.75 (top quartile of viewed
--                    products, among products with >= 1 view)
--   low_purchases -> conversion_percentile <= 0.50 (at/below the median
--                    conversion rate)
--   A product must satisfy BOTH to be flagged is_high_view_low_purchase.
--   The percentile values themselves are exposed as columns so the cutoff
--   is auditable and can be changed in Looker Studio without re-deriving it.
-- Performance : PERCENT_RANK() runs over the already-aggregated per-product
--               CTE (one row per product, not one row per event), so the
--               window function never touches the large fact table directly.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_product_high_views_low_purchases` AS
WITH agg AS (
  SELECT
    product_key,
    SUM(is_view) AS views,
    SUM(is_cart) AS carts,
    SUM(is_purchase) AS purchases
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY product_key
),
scored AS (
  SELECT
    a.*,
    SAFE_DIVIDE(a.purchases, a.views) AS conversion_rate,
    PERCENT_RANK() OVER (ORDER BY a.views) AS views_percentile,
    PERCENT_RANK() OVER (ORDER BY SAFE_DIVIDE(a.purchases, a.views)) AS conversion_percentile
  FROM agg a
  WHERE a.views > 0
)
SELECT
  p.product_key,
  p.product_id,
  c.category_code,
  c.category_name,
  b.brand,
  s.views,
  s.carts,
  s.purchases,
  s.conversion_rate,
  s.views_percentile,
  s.conversion_percentile,
  (s.views_percentile >= 0.75 AND s.conversion_percentile <= 0.50) AS is_high_view_low_purchase
FROM scored s
JOIN `shop-sense-project.shopsense_analytics_gold.dim_product` p ON p.product_key = s.product_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = p.category_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand` b ON b.brand_key = p.brand_key;
