-- =============================================================================
-- View: vw_conversion_trend
--
-- Dashboard requirement: "How does conversion change daily/weekly/monthly?" +
-- "Revenue Over Time" (daily / weekly / monthly revenue trend).
--
-- Grain       : one row per calendar day (from dim_date). year/quarter/month/
--               month_name/week/day_of_week/is_weekend all ride on the same
--               row, so Looker Studio can group to daily, weekly or monthly
--               using its own date-grouping control - one reusable view
--               instead of separate daily/weekly/monthly views.
-- Source      : fact_events, dim_date.
-- EXTENDED    : `revenue` and `avg_purchase_value` were added so this one view
--               also serves the "revenue over time" requirement - a separate
--               vw_revenue_daily would duplicate ~90% of these columns.
--               `daily_active_users` / `daily_sessions` were added for a DAU
--               line chart.
-- Join        : dim_date only covers the date range actually present in
--               Silver, so every date_key produced by aggregating fact_events
--               finds a matching dim_date row - INNER JOIN is safe (dim_date
--               is one row per day, no fan-out).
--
-- Date filter : filter date_key in the BI tool. The ADDITIVE columns
--               (views/carts/purchases/revenue) SUM correctly over any range;
--               the rate columns and avg_purchase_value are per-day and MUST
--               be recomputed from the summed components for a multi-day
--               range (SUM(purchases)/SUM(views), SUM(revenue)/SUM(purchases)).
-- Weekly/monthly: group by (year, month) or (year, week) - never month or week
--               alone (not unique across years).
-- NON-ADDITIVE : daily_active_users and daily_sessions are correct for THEIR
--               day only. Use AVG() across days for a "typical daily active
--               users" figure; NEVER SUM() them - a weekly/monthly unique
--               user count needs a finer (date_key, user_id) grain, or the
--               all-time figure from vw_business_summary.
-- Every rate uses SAFE_DIVIDE (NULL, never an error, on a zero denominator).
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_conversion_trend` AS
WITH agg AS (
  SELECT
    date_key,
    SUM(is_view)                       AS views,
    SUM(is_cart)                       AS carts,
    SUM(is_purchase)                   AS purchases,
    SUM(IF(is_purchase = 1, price, 0)) AS revenue,
    COUNT(DISTINCT user_id)            AS daily_active_users,  -- NON-ADDITIVE across days
    COUNT(DISTINCT session_key)        AS daily_sessions       -- NON-ADDITIVE across days
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY date_key
)
SELECT
  d.date_key,
  d.year,
  d.quarter,
  d.month,
  d.month_name,
  d.week,
  d.day_of_week,
  d.is_weekend,
  a.views,
  a.carts,
  a.purchases,
  a.revenue,
  a.daily_active_users,
  a.daily_sessions,
  SAFE_DIVIDE(a.carts, a.views)         AS view_to_cart_rate,
  SAFE_DIVIDE(a.purchases, a.carts)     AS cart_to_purchase_rate,
  SAFE_DIVIDE(a.purchases, a.views)     AS view_to_purchase_rate,
  SAFE_DIVIDE(a.revenue, a.purchases)   AS avg_purchase_value
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_date` d ON d.date_key = a.date_key;
