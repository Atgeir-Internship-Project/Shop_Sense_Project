-- =============================================================================
-- View: vw_price_conversion
--
-- Dashboard requirement: "Does product price affect conversion rate?"
--
-- Grain       : one row per product_id (all-time).
-- Source      : fact_events, dim_product, dim_category, dim_brand.
-- avg_price   : dim_product has no price column by design (price lives only
--               on fact_events, per the Gold schema notes - a product's
--               price can legitimately vary event to event, e.g. a sale).
--               A single representative price per product is needed for
--               plotting/banding, so this uses AVG(price) across that
--               product's events - documented here rather than assumed.
-- price_quintile = NTILE(5) over the price distribution of products with at
--               least one view - a data-driven split into 5 equal-sized
--               groups, not fixed dollar cutoffs (there is no stated
--               business reason for specific price breakpoints, so an
--               arbitrary $0-50/$50-100/... scheme was avoided).
-- This view does NOT compute a single correlation number - it returns
--               product-level rows (price, quintile, conversion_rate) so
--               Looker Studio can build a scatter plot or a bar chart of
--               conversion_rate by price_quintile and let the relationship
--               (if any) show itself, per the requirement to avoid a single
--               reductive correlation value.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_price_conversion` AS
WITH agg AS (
  SELECT
    product_key,
    AVG(price) AS avg_price,
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
    NTILE(5) OVER (ORDER BY a.avg_price) AS price_quintile
  FROM agg a
  WHERE a.views > 0
)
SELECT
  p.product_key,
  p.product_id,
  c.category_code,
  c.category_name,
  b.brand,
  s.avg_price,
  s.price_quintile,
  s.views,
  s.carts,
  s.purchases,
  s.conversion_rate
FROM scored s
JOIN `shop-sense-project.shopsense_analytics_gold.dim_product` p ON p.product_key = s.product_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = p.category_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand` b ON b.brand_key = p.brand_key;
