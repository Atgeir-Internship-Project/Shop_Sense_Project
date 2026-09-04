-- =============================================================================
-- View: vw_dashboard_overview
--
-- THE single data source for Page 1 of the ShopSense Looker Studio dashboard
-- ("Business Overview"). Every Page 1 tile - the KPI scorecards, the shopping
-- funnel, the conversion trend, the revenue trend, revenue by category / brand
-- and the drop-off chart - reads from this one view, so a single Date Range
-- Control plus a Category filter and a Brand filter drive all of them
-- consistently.
--
-- Supersedes vw_category_daily_summary (coarser grain). Retire that view and
-- repoint its tiles here.
--
-- ---------------------------------------------------------------------------
-- Grain: ONE ROW PER (date_key, category_key, brand_key)
-- ---------------------------------------------------------------------------
-- category_key is the EXACT category tagged on the event (the leaf level of
-- category_code); brand_key is the event's brand. This is the finest
-- date / category / brand grain in the data: every event contributes to
-- exactly one row, so views / carts / purchases / revenue stay FULLY ADDITIVE.
-- Looker Studio rolls them up to weekly / monthly, or across categories /
-- brands, with plain SUM() and never double-counts.
--
-- ---------------------------------------------------------------------------
-- Hierarchy filtering (unchanged)
-- ---------------------------------------------------------------------------
-- Events are tagged at the category leaf (e.g. electronics.audio.headphone), so
-- a filter on category_name = 'Electronics' matches almost nothing. This view
-- denormalises the ANCESTOR path onto every row - category_l1 / l2 / l3 / l4
-- (+ the _code twins) - resolved once from bridge_category_hierarchy in the
-- `category_path` CTE, which is grouped to EXACTLY ONE ROW PER category_key, so
-- the join cannot introduce duplicate rows. Filtering category_l1 =
-- 'electronics' matches every leaf row under electronics, each event still
-- counted EXACTLY ONCE.
--
-- category_l4 / category_l4_code (added): the level-4 ancestor, resolved the
-- same way as l1/l2/l3 - filtered to level_number = 4 in the ancestor
-- closure. For a category with only 3 levels there IS no level-4 ancestor, so
-- these stay NULL - never backfilled from category_name, which would wrongly
-- duplicate the leaf (e.g. a 3-level path's L3 also appearing as "L4").
--
-- ---------------------------------------------------------------------------
-- Sources & fan-out
-- ---------------------------------------------------------------------------
-- fact_events, dim_brand, dim_category, dim_date, bridge_category_hierarchy.
-- fact_events is aggregated to (date, category, brand) in the `agg` CTE FIRST,
-- BEFORE any dimension join; every subsequent join (dim_brand, dim_category,
-- dim_date, category_path) is one-row-per-key, so nothing is multiplied and
-- the grain is preserved.
--
-- ---------------------------------------------------------------------------
-- Rate columns - DISPLAY ONLY
-- ---------------------------------------------------------------------------
--   view_to_cart_rate      = carts / views        PER (day, category, brand) ONLY
--   cart_to_purchase_rate  = purchases / carts     PER (day, category, brand) ONLY
--   view_to_purchase_rate  = purchases / views     PER (day, category, brand) ONLY
-- In Looker Studio these MUST NOT be SUMmed or AVERAGEd for any rolled-up
-- figure. Recompute from the additive columns:
--   SUM(carts)/SUM(views) , SUM(purchases)/SUM(carts) , SUM(purchases)/SUM(views).
-- The additive numerators / denominators (views, carts, purchases) are exposed
-- for exactly this reason.
--
-- ---------------------------------------------------------------------------
-- cart_to_purchase_rate CAVEAT - do not "fix" this
-- ---------------------------------------------------------------------------
-- Event-level ratio. The source has no cart / order identifier linking a cart
-- event to a later purchase, so `purchases` and `carts` are independent event
-- counts. For a (day, category, brand) slice it can legitimately EXCEED 100% -
-- buy-now purchases with no cart event, or a cart placed on an earlier day. It
-- is NOT capped, by design. Same definition as vw_category_cart_purchase_dropout
-- and vw_conversion_trend.
--
-- Revenue = SUM(price) over is_purchase = 1 rows only - identical to
-- vw_category_revenue, vw_conversion_trend and vw_business_summary. Never
-- computed from view or cart rows.
--
-- NOT in this view: distinct user / session counts. They are non-additive at
-- this grain and belong in vw_business_summary.
--
-- Identifier fields (brand_key, category_key, parent_category_key) are cast to
-- STRING in the final SELECT. They are FARM_FINGERPRINT hashes - very large
-- signed integers that are labels, not measures. Left as INT64, Looker Studio
-- auto-classifies them as metrics and SUMs them, which overflows INT64
-- ("Error in SUM aggregation: integer overflow"). As STRING they can only be
-- used as dimensions, which is all they are for. The join keys inside the CTEs
-- remain INT64 and unchanged.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_dashboard_overview` AS
WITH agg AS (
  -- fact_events -> exact (date, category, brand) grain, BEFORE any dimension join
  SELECT
    date_key,
    category_key,
    brand_key,
    SUM(is_view)                       AS views,
    SUM(is_cart)                       AS carts,
    SUM(is_purchase)                   AS purchases,
    SUM(IF(is_purchase = 1, price, 0)) AS revenue
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY date_key, category_key, brand_key
),
category_path AS (
  -- each category_key -> the NAME and CODE of its level-1 / 2 / 3 / 4
  -- ancestor, resolved once from the closure table. GROUP BY guarantees
  -- exactly one row per category_key, so the LEFT JOIN below cannot add
  -- duplicate rows. A category with fewer than 4 levels simply has no
  -- level_number = 4 row in its ancestor set, so category_l4(/_code) comes
  -- back NULL from the MAX(IF(...)) - never artificially populated.
  SELECT
    bh.descendant_category_key AS category_key,
    MAX(IF(anc.level_number = 1, anc.category_name, NULL)) AS category_l1,
    MAX(IF(anc.level_number = 1, anc.category_code, NULL)) AS category_l1_code,
    MAX(IF(anc.level_number = 2, anc.category_name, NULL)) AS category_l2,
    MAX(IF(anc.level_number = 2, anc.category_code, NULL)) AS category_l2_code,
    MAX(IF(anc.level_number = 3, anc.category_name, NULL)) AS category_l3,
    MAX(IF(anc.level_number = 3, anc.category_code, NULL)) AS category_l3_code,
    MAX(IF(anc.level_number = 4, anc.category_name, NULL)) AS category_l4,
    MAX(IF(anc.level_number = 4, anc.category_code, NULL)) AS category_l4_code
  FROM `shop-sense-project.shopsense_analytics_gold.bridge_category_hierarchy` bh
  JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` anc
    ON anc.category_key = bh.ancestor_category_key
  GROUP BY bh.descendant_category_key
)
SELECT
  -- ---- 1. date : the Date Range Control binds to date_key ----
  a.date_key,
  d.year,
  d.month,
  d.month_name,
  d.week,
  FORMAT_DATE('%Y-%m',  a.date_key)  AS year_month,   -- "2019-10"  : safe monthly bucket, sorts chronologically
  FORMAT_DATE('%G-W%V', a.date_key)  AS year_week,     -- "2019-W40" : ISO year + ISO week, unique across years

  -- ---- 2. brand ----
  CAST(a.brand_key AS STRING) AS brand_key,                        -- STRING: hashed id (FARM_FINGERPRINT), a label
                                                                   --         not a number. Looker SUMs INT64 ids and
                                                                   --         overflows - see note above.
  b.brand,                                                         -- <-- the Brand dropdown

  -- ---- 3. category ----
  CAST(a.category_key AS STRING) AS category_key,                  -- STRING: hashed id, a label not a number
  c.category_name,                                                 -- exact / leaf, human-readable
  c.category_code,                                                 -- full dotted path
  CAST(c.parent_category_key AS STRING) AS parent_category_key,    -- STRING: hashed id, a label not a number (NULL at top)
  c.level_number,
  c.is_leaf,

  -- ---- 4. category hierarchy (denormalised ancestor path) ----
  COALESCE(p.category_l1,      c.category_name) AS category_l1,     -- <-- the primary Category dropdown
  COALESCE(p.category_l1_code, c.category_code) AS category_l1_code,
  p.category_l2,
  p.category_l2_code,
  p.category_l3,
  p.category_l3_code,
  p.category_l4,                                                    -- NULL unless the path is actually 4 levels deep
  p.category_l4_code,

  -- ---- 5. additive business metrics : SUM() these in Looker ----
  a.views,
  a.carts,
  a.purchases,
  a.revenue,

  -- ---- 6. per-(day, category, brand) rates : DISPLAY ONLY, never SUM / AVG ----
  SAFE_DIVIDE(a.carts,     a.views) AS view_to_cart_rate,
  SAFE_DIVIDE(a.purchases, a.carts) AS cart_to_purchase_rate,      -- event-level; may exceed 1.0, not capped
  SAFE_DIVIDE(a.purchases, a.views) AS view_to_purchase_rate
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand` b
  ON b.brand_key = a.brand_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c
  ON c.category_key = a.category_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_date` d
  ON d.date_key = a.date_key
LEFT JOIN category_path p
  ON p.category_key = a.category_key;
