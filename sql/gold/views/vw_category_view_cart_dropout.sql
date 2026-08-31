-- =============================================================================
-- View: vw_category_view_cart_dropout
--
-- Dashboard requirement: "Which categories have the highest view -> cart
-- drop-off?"
--
-- Grain       : one row per (category, date)
-- Source      : fact_events, dim_category
-- Metric type : aggregate/macro conversion (event-count ratio) - total cart
--               events over total view events in the category, not whether
--               any one specific view event was followed by a cart. There is
--               no cart/order id in the schema to link a specific view to a
--               specific cart, so a session-sequential funnel isn't possible
--               here; this is the standard definition used for category/
--               product-level funnel dashboards.
-- Category grain: the exact category_code level tagged on the event. Not
--               rolled up through bridge_category_hierarchy - a category and
--               its sub-categories are separate rows here.
-- NULLs/UNKNOWN : category_key = -1 ('UNKNOWN') is included like any other
--               category, not filtered out.
-- Division by 0 : SAFE_DIVIDE returns NULL when views = 0 for that category/
--               day, rather than erroring or showing a false 0%/100%.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_category_view_cart_dropout` AS
WITH agg AS (
  -- Aggregate the large fact table down to (category, date) BEFORE joining
  -- to the tiny dimension table, so the join never touches fact-table rows.
  SELECT
    category_key,
    date_key,
    SUM(is_view) AS views,
    SUM(is_cart) AS carts
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY category_key, date_key
)
SELECT
  c.category_key,
  c.category_code,
  c.category_name,
  a.date_key,
  a.views,
  a.carts,
  SAFE_DIVIDE(a.carts, a.views) AS view_to_cart_rate,
  1 - SAFE_DIVIDE(a.carts, a.views) AS view_to_cart_dropoff
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c
  ON c.category_key = a.category_key;
