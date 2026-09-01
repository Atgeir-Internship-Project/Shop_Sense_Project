-- =============================================================================
-- View: vw_brand_engagement_conversion
--
-- Dashboard requirement: "Which brands have high engagement but low
-- conversion?"
--
-- Grain       : one row per brand (all-time).
-- Source      : fact_events, dim_brand.
-- engagement   = views + carts. Both signal a user interacting with a
--               brand's products short of buying. remove_from_cart is not
--               included - it does not occur in this dataset (confirmed
--               during Silver profiling).
-- Threshold definition (percentile-based, not an arbitrary fixed number):
--   high_engagement -> engagement_percentile >= 0.75 (top quartile)
--   low_conversion  -> conversion_percentile <= 0.25 (bottom quartile),
--                       where conversion_rate = purchases / engagement
--   A brand must satisfy BOTH to be flagged
--   is_high_engagement_low_conversion. Percentiles are exposed as columns
--   so the cutoff is auditable and adjustable in Looker Studio without
--   re-deriving them.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_brand_engagement_conversion` AS
WITH agg AS (
  SELECT
    brand_key,
    SUM(is_view) AS views,
    SUM(is_cart) AS carts,
    SUM(is_purchase) AS purchases,
    SUM(is_view) + SUM(is_cart) AS engagement
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY brand_key
),
scored AS (
  SELECT
    a.*,
    SAFE_DIVIDE(a.purchases, a.engagement) AS conversion_rate,
    PERCENT_RANK() OVER (ORDER BY a.engagement) AS engagement_percentile,
    PERCENT_RANK() OVER (ORDER BY SAFE_DIVIDE(a.purchases, a.engagement)) AS conversion_percentile
  FROM agg a
  WHERE a.engagement > 0
)
SELECT
  b.brand_key,
  b.brand,
  s.views,
  s.carts,
  s.purchases,
  s.engagement,
  s.conversion_rate,
  s.engagement_percentile,
  s.conversion_percentile,
  (s.engagement_percentile >= 0.75 AND s.conversion_percentile <= 0.25) AS is_high_engagement_low_conversion
FROM scored s
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand` b ON b.brand_key = s.brand_key;
