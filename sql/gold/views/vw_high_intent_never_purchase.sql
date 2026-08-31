-- =============================================================================
-- View: vw_high_intent_never_purchase
--
-- Dashboard requirement: "Who are the high-intent users who never purchase?"
--
-- Grain       : one row per user_id (all-time roster, not a trend - "who
--               are" asks for a list of people, not a time series).
-- Source      : fact_events only.
-- High-intent definition: a user with at least one cart event and zero
--               purchase events. This matches the definition already
--               validated elsewhere in this project (Business Question 2 in
--               cloud_functions/silver_to_gold/validation_queries.sql) -
--               kept consistent rather than inventing a second definition.
-- remove_from_cart is NOT included as a signal: this event type does not
--               occur in the dataset (confirmed during Silver profiling -
--               only view/cart/purchase exist), so there is nothing to add.
-- The view already filters to just the qualifying users (that is its whole
--               purpose) - it is not a general per-user stats table.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_high_intent_never_purchase` AS
SELECT
  user_id,
  SUM(is_view) AS views,
  SUM(is_cart) AS carts,
  SUM(is_purchase) AS purchases,
  COUNT(DISTINCT session_key) AS sessions
FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
WHERE user_id IS NOT NULL
GROUP BY user_id
HAVING SUM(is_cart) > 0 AND SUM(is_purchase) = 0;
