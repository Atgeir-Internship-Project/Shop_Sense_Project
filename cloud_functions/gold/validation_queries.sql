-- =============================================================================
-- Gold-layer validation queries for the ShopSense project.
--
-- Run each block on its own, e.g.
--   bq query --use_legacy_sql=false "<paste one block>"
--
-- Project  : shop-sense-project
-- Datasets : shopsense_analytics_silver (source), shopsense_analytics_gold
--
-- Order of use:
--   0. RUN STATUS      - did the build succeed, what do its own metrics say
--   1-4. INTEGRITY     - row counts, no dupes, no orphan FKs, sane dim sizes
--   5-8. PROFILE       - cross-check against the validated dataset facts
--   Q1-Q3. BUSINESS    - the model answers real questions
-- =============================================================================


-- -----------------------------------------------------------------------------
-- RUN STATUS 0 - the function's own recorded metrics
-- status must be SUCCESS; fk_resolution_failures and duplicate_event_keys
-- must be 0; fact_events_total must equal silver_rows.
-- -----------------------------------------------------------------------------
SELECT *
FROM `shop-sense-project.shopsense_analytics_gold.ingestion_insight_control`
ORDER BY ingestion_timestamp DESC
LIMIT 5;


-- -----------------------------------------------------------------------------
-- INTEGRITY CHECK 1 - fact_events row count matches Silver exactly
-- Silver holds only view/cart/purchase rows, so once every batch has been
-- processed the two counts must be equal (no more = no duplicate insert,
-- no less = no dropped events).
-- -----------------------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM `shop-sense-project.shopsense_analytics_gold.fact_events`)          AS fact_rows,
  (SELECT COUNT(*) FROM `shop-sense-project.shopsense_analytics_silver.transform_data_table`) AS silver_rows;


-- -----------------------------------------------------------------------------
-- INTEGRITY CHECK 2 - no duplicate event_key in fact_events
-- Expect n_dupes = 0. If the MERGE key were wrong a re-run would show > 0.
-- -----------------------------------------------------------------------------
SELECT
  COUNT(*)                    AS total_rows,
  COUNT(DISTINCT event_key)   AS distinct_event_keys,
  COUNT(*) - COUNT(DISTINCT event_key) AS n_dupes
FROM `shop-sense-project.shopsense_analytics_gold.fact_events`;


-- -----------------------------------------------------------------------------
-- INTEGRITY CHECK 3 - no unresolved foreign keys in fact_events
-- Every *_key (including the -1 UNKNOWN members) must point at a real row.
-- Expect all four counts = 0.
-- -----------------------------------------------------------------------------
SELECT
  COUNTIF(p.product_key   IS NULL) AS missing_product_key,
  COUNTIF(c.category_key  IS NULL) AS missing_category_key,
  COUNTIF(b.brand_key     IS NULL) AS missing_brand_key,
  COUNTIF(s.session_key   IS NULL) AS missing_session_key
FROM `shop-sense-project.shopsense_analytics_gold.fact_events` f
LEFT JOIN `shop-sense-project.shopsense_analytics_gold.dim_product`  p ON p.product_key  = f.product_key
LEFT JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = f.category_key
LEFT JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand`    b ON b.brand_key    = f.brand_key
LEFT JOIN `shop-sense-project.shopsense_analytics_gold.dim_session`  s ON s.session_key  = f.session_key;


-- -----------------------------------------------------------------------------
-- INTEGRITY CHECK 4 - dimension row counts are sane
-- dim_category ~159, dim_product ~165K.
-- -----------------------------------------------------------------------------
SELECT 'dim_date'     AS table_name, COUNT(*) AS n FROM `shop-sense-project.shopsense_analytics_gold.dim_date`
UNION ALL SELECT 'dim_category',            COUNT(*) FROM `shop-sense-project.shopsense_analytics_gold.dim_category`
UNION ALL SELECT 'bridge_category_hierarchy', COUNT(*) FROM `shop-sense-project.shopsense_analytics_gold.bridge_category_hierarchy`
UNION ALL SELECT 'dim_brand',               COUNT(*) FROM `shop-sense-project.shopsense_analytics_gold.dim_brand`
UNION ALL SELECT 'dim_product',             COUNT(*) FROM `shop-sense-project.shopsense_analytics_gold.dim_product`
UNION ALL SELECT 'dim_session',             COUNT(*) FROM `shop-sense-project.shopsense_analytics_gold.dim_session`
UNION ALL SELECT 'fact_events',             COUNT(*) FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
ORDER BY table_name;


-- =============================================================================
-- BUSINESS QUESTION 1
-- Category drop-off (view -> cart) for the last 7 days, grouped by category.
-- =============================================================================
SELECT
  c.category_code,
  c.category_name,
  SUM(f.is_view)                                            AS views,
  SUM(f.is_cart)                                            AS carts,
  SAFE_DIVIDE(SUM(f.is_cart), SUM(f.is_view))               AS cart_rate,
  1 - SAFE_DIVIDE(SUM(f.is_cart), SUM(f.is_view))           AS view_to_cart_dropoff
FROM `shop-sense-project.shopsense_analytics_gold.fact_events` f
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c
  ON c.category_key = f.category_key
WHERE f.date_key >= DATE_SUB(
        (SELECT MAX(date_key) FROM `shop-sense-project.shopsense_analytics_gold.fact_events`),
        INTERVAL 7 DAY)
  AND f.category_key != -1
GROUP BY c.category_code, c.category_name
HAVING views > 0
ORDER BY view_to_cart_dropoff DESC;


-- =============================================================================
-- BUSINESS QUESTION 2
-- High-intent-but-never-purchase users: viewed AND carted, zero purchases.
-- =============================================================================
SELECT
  f.user_id,
  SUM(f.is_view)     AS views,
  SUM(f.is_cart)     AS carts,
  SUM(f.is_purchase) AS purchases
FROM `shop-sense-project.shopsense_analytics_gold.fact_events` f
GROUP BY f.user_id
HAVING SUM(f.is_view) > 0
   AND SUM(f.is_cart) > 0
   AND SUM(f.is_purchase) = 0
ORDER BY carts DESC, views DESC
LIMIT 100;


-- =============================================================================
-- BUSINESS QUESTION 3
-- Electronics vs Apparel funnel, rolled up through the bridge table
-- (no string matching on category_code).
-- =============================================================================
WITH roots AS (
  SELECT category_key, category_name
  FROM `shop-sense-project.shopsense_analytics_gold.dim_category`
  WHERE level_number = 1
    AND LOWER(category_name) IN ('electronics', 'apparel')
),
-- every category that rolls up to one of those roots
in_scope AS (
  SELECT r.category_name AS root_name, b.descendant_category_key AS category_key
  FROM roots r
  JOIN `shop-sense-project.shopsense_analytics_gold.bridge_category_hierarchy` b
    ON b.ancestor_category_key = r.category_key
)
SELECT
  s.root_name,
  SUM(f.is_view)     AS views,
  SUM(f.is_cart)     AS carts,
  SUM(f.is_purchase) AS purchases,
  SAFE_DIVIDE(SUM(f.is_cart),     SUM(f.is_view)) AS view_to_cart,
  SAFE_DIVIDE(SUM(f.is_purchase), SUM(f.is_cart)) AS cart_to_purchase
FROM `shop-sense-project.shopsense_analytics_gold.fact_events` f
JOIN in_scope s ON s.category_key = f.category_key
GROUP BY s.root_name
ORDER BY s.root_name;
