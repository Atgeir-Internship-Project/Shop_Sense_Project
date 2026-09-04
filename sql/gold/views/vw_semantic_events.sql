-- =============================================================================
-- View: vw_semantic_events   (SEMANTIC-LAYER BASE VIEW - not a dashboard tile)
--
-- Purpose: the single wide, denormalised, event-grain view that the ShopSense
-- semantic layer (semantic/) and the GenAI agent build every query against.
-- The 14 pre-aggregated vw_* views feed Looker tiles; THIS view is the one
-- the agent's deterministic SQL builder targets, so metric maths lives in the
-- catalog (semantic/metrics.yaml) once and is never re-invented per question.
--
-- Grain       : one row per event (identical to fact_events - one view / cart
--               / purchase). SUM(is_view/is_cart/is_purchase) and
--               SUM(IF(is_purchase = 1, price, 0)) are the additive building
--               blocks; COUNT(DISTINCT user_id / session_key) the non-additive
--               ones.
-- Source      : fact_events + all dimensions, joined at event grain.
-- Joins       : dim_date / dim_category / dim_brand / dim_product are INNER -
--               every fact_events FK resolves (fk_resolution_failures = 0 is a
--               pipeline invariant, checked in validation_queries.sql), and
--               each dim is one row per key, so there is no fan-out.
-- category_l1 : the top-of-tree (level 1) ancestor category name, resolved
--               once via the cat_l1 CTE over bridge_category_hierarchy (each
--               category has exactly one level-1 ancestor). This is what makes
--               "Electronics vs Apparel" style roll-up questions answerable
--               without string-matching on category_code. UNKNOWN (level 0)
--               has no level-1 ancestor -> 'UNKNOWN'.
-- Dates       : the data is historical (2019-10 / 2019-11). Relative windows
--               ("this week") are anchored on MAX(event_date) in the semantic
--               layer, never CURRENT_DATE.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_semantic_events` AS
WITH cat_l1 AS (
  -- category_key -> its single level-1 (top-of-tree) ancestor name
  SELECT
    bh.descendant_category_key AS category_key,
    anc.category_name          AS category_l1
  FROM `shop-sense-project.shopsense_analytics_gold.bridge_category_hierarchy` bh
  JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` anc
    ON anc.category_key = bh.ancestor_category_key
   AND anc.level_number = 1
)
SELECT
  f.event_time,
  f.date_key                            AS event_date,
  d.year,
  d.quarter,
  d.month,
  d.month_name,
  d.week                                AS iso_week,
  d.day_of_week,
  d.is_weekend,
  f.event_type,
  f.is_view,
  f.is_cart,
  f.is_purchase,
  f.price,
  f.user_id,
  f.session_key,
  f.product_key,
  p.product_id,
  b.brand,
  f.category_key,
  c.category_code,
  c.category_name,
  c.level_number                        AS category_level,
  COALESCE(cl1.category_l1, 'UNKNOWN')  AS category_l1
FROM `shop-sense-project.shopsense_analytics_gold.fact_events` f
JOIN `shop-sense-project.shopsense_analytics_gold.dim_date`     d ON d.date_key     = f.date_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = f.category_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand`    b ON b.brand_key    = f.brand_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_product`  p ON p.product_key  = f.product_key
LEFT JOIN cat_l1 cl1 ON cl1.category_key = f.category_key;
