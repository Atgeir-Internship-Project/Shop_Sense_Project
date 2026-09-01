-- =============================================================================
-- View: vw_business_summary
--
-- Dashboard requirement: "Show Overview" - the main KPI-level summary for the
-- ShopSense executive Overview dashboard.
--
-- Grain       : ONE ROW - the entire fact_events dataset (all dates, all
--               categories, all brands). This is deliberate: the distinct
--               user / session counts below are period totals and can only be
--               computed correctly by counting DISTINCT once over the whole
--               table. They must NEVER be reconstructed by summing a per-day
--               distinct count (a user active on 5 days would be counted 5x).
-- Source      : fact_events only.
-- Date filter : NONE. This view is pre-aggregated and cannot be filtered by
--               date in the BI tool. For date-range KPIs, build the Overview
--               scorecards on vw_conversion_trend and aggregate there:
--               SUM() the additive columns (views/carts/purchases/revenue),
--               recompute the rates from those sums, and use AVG() - never
--               SUM() - on daily_active_users / daily_sessions.
--
-- Metric formulas:
--   total_events              = COUNT(*)  ( = SUM(event_count) = views+carts+purchases )
--   total_revenue             = SUM(price) WHERE is_purchase = 1
--   conversion_rate           = total_purchases / total_views          (view -> purchase)
--   view_to_cart_rate         = total_carts     / total_views
--   cart_to_purchase_rate     = total_purchases / total_carts
--   avg_purchase_value        = total_revenue   / total_purchases      (per purchase EVENT,
--                               not per order - the schema has no order/basket grain)
--   avg_purchasing_session_value = total_revenue / #sessions with >=1 purchase  (AOV proxy)
--   revenue_per_user          = total_revenue / total_unique_users     (ARPU, all users)
--   revenue_per_purchasing_user = total_revenue / total_purchasing_users
-- Every division uses SAFE_DIVIDE (NULL, never an error, on a zero denominator).
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_business_summary` AS
WITH base AS (
  SELECT
    COUNT(DISTINCT user_id)                                AS total_unique_users,
    COUNT(DISTINCT session_key)                            AS total_unique_sessions,
    COUNT(*)                                               AS total_events,
    SUM(is_view)                                           AS total_views,
    SUM(is_cart)                                           AS total_carts,
    SUM(is_purchase)                                       AS total_purchases,
    SUM(IF(is_purchase = 1, price, 0))                     AS total_revenue,
    COUNT(DISTINCT IF(is_purchase = 1, user_id, NULL))     AS total_purchasing_users,
    COUNT(DISTINCT IF(is_purchase = 1, session_key, NULL)) AS total_purchasing_sessions
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
)
SELECT
  total_unique_users,
  total_unique_sessions,
  total_events,
  total_views,
  total_carts,
  total_purchases,
  total_purchasing_users,
  total_revenue,
  SAFE_DIVIDE(total_purchases, total_views)               AS conversion_rate,
  SAFE_DIVIDE(total_carts, total_views)                   AS view_to_cart_rate,
  SAFE_DIVIDE(total_purchases, total_carts)               AS cart_to_purchase_rate,
  SAFE_DIVIDE(total_revenue, total_purchases)             AS avg_purchase_value,
  SAFE_DIVIDE(total_revenue, total_purchasing_sessions)   AS avg_purchasing_session_value,
  SAFE_DIVIDE(total_revenue, total_unique_users)          AS revenue_per_user,
  SAFE_DIVIDE(total_revenue, total_purchasing_users)      AS revenue_per_purchasing_user
FROM base;
