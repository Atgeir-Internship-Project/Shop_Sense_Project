-- =============================================================================
-- View: vw_product_conversion
--
-- Dashboard requirement: "Which products have the highest conversion rate?"
--
-- Grain       : one row per product_id (all-time).
-- Source      : fact_events, dim_product, dim_category, dim_brand.
-- conversion_rate = purchases / views (SAFE_DIVIDE - NULL when views = 0).
-- Minimum-volume rule: a product needs >= 30 views to be eligible for
--               ranking - a standard small-sample-size floor (so a product
--               with 1 view and 1 purchase, a "100% conversion rate", does
--               not outrank a product with thousands of views and a
--               genuinely strong rate). Products below the floor are NOT
--               dropped - they still appear with qualifies_for_ranking =
--               FALSE and conversion_rank = NULL, so nothing is hidden.
-- Ranking correctness: RANK() is computed only over the qualifying subset
--               (see the `ranked` CTE) - if it ran over every product and
--               were merely hidden for non-qualifying rows, the qualifying
--               ranks would have gaps left by disqualified high-rate/
--               low-volume products. Restricting the window's input avoids
--               that.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_product_conversion` AS
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
    a.views >= 30 AS qualifies_for_ranking
  FROM agg a
),
ranked AS (
  -- RANK() only sees qualifying rows, so ranks stay dense (1, 2, 3, ...)
  -- among products that actually meet the volume floor.
  SELECT
    product_key,
    RANK() OVER (ORDER BY conversion_rate DESC) AS conversion_rank
  FROM scored
  WHERE qualifies_for_ranking
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
  s.qualifies_for_ranking,
  r.conversion_rank
FROM scored s
LEFT JOIN ranked r ON r.product_key = s.product_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_product` p ON p.product_key = s.product_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = p.category_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand` b ON b.brand_key = p.brand_key;
