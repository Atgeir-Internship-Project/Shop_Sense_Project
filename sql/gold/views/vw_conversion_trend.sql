-- =============================================================================
-- View: vw_conversion_trend
--
-- Dashboard requirement: "How does conversion change daily/weekly/monthly?"
--
-- Grain       : one row per calendar day (from dim_date). year/month/
--               month_name/week/day_of_week/is_weekend all ride on the same
--               row, so Looker Studio can group by whichever grain a chart
--               needs using its own date-grouping control - one reusable
--               view instead of three near-duplicate daily/weekly/monthly
--               views.
-- Source      : fact_events, dim_date.
-- Join        : dim_date only covers the date range actually present in
--               Silver, so every date_key produced by aggregating
--               fact_events is guaranteed to find a matching dim_date row -
--               an INNER JOIN is safe here (no fan-out risk since dim_date
--               is one row per day).
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_conversion_trend` AS
WITH agg AS (
  SELECT
    date_key,
    SUM(is_view) AS views,
    SUM(is_cart) AS carts,
    SUM(is_purchase) AS purchases
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY date_key
)
SELECT
  d.date_key,
  d.year,
  d.month,
  d.month_name,
  d.week,
  d.day_of_week,
  d.is_weekend,
  a.views,
  a.carts,
  a.purchases,
  SAFE_DIVIDE(a.carts, a.views) AS view_to_cart_rate,
  SAFE_DIVIDE(a.purchases, a.carts) AS cart_to_purchase_rate,
  SAFE_DIVIDE(a.purchases, a.views) AS view_to_purchase_rate
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_date` d ON d.date_key = a.date_key;
