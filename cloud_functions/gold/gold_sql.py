"""
Builds the one BigQuery script that (re)loads the whole Gold layer.

All of the work runs inside BigQuery; the Cloud Function only submits
this text and reads back a single row of counts.

Order of statements (dependencies flow downward):

    1. dim_date                    <- Silver.event_time range
    2. dim_category                <- distinct Silver.category_code, exploded
    3. bridge_category_hierarchy   <- recursive over dim_category
    4. dim_brand                   <- distinct Silver.brand
    5. dim_product                 <- Silver grouped by product_id (+ dims)
    6. dim_session                 <- Silver grouped by user_session
    7. fact_events  MERGE          <- Silver rows (+ dims), keyed on event_key
    8. metrics SELECT              <- row counts + integrity checks

Idempotency:
  * steps 1-6 are CREATE OR REPLACE - deterministic rebuilds. Every key is
    a FARM_FINGERPRINT of the business value, so re-running just recreates
    the identical rows. There is no append, so nothing can be duplicated.
  * step 7 is a MERGE keyed on event_key (= Silver's surrogate_key). A
    second run against the same Silver data matches every row and inserts
    nothing. This is the one table where a re-run could otherwise
    double-insert, which is why it is a MERGE and not CREATE OR REPLACE.

fact_events.event_count is a constant 1 (a countable grain marker):
SUM(event_count) = number of events, and it always equals
is_view + is_cart + is_purchase.
"""

from config import (
    BRIDGE_CATEGORY,
    DIM_BRAND,
    DIM_CATEGORY,
    DIM_DATE,
    DIM_PRODUCT,
    DIM_SESSION,
    FACT_EVENTS,
    gold_table_id,
    silver_table_id,
)
from schemas import (
    BRIDGE_CATEGORY_COLUMNS,
    DIM_BRAND_COLUMNS,
    DIM_CATEGORY_COLUMNS,
    DIM_DATE_COLUMNS,
    DIM_PRODUCT_COLUMNS,
    DIM_SESSION_COLUMNS,
)

_FACT_INSERT_COLUMNS = (
    "event_key, event_time, date_key, event_type, product_key, "
    "category_key, brand_key, session_key, user_id, category_id, price, "
    "event_count, is_view, is_cart, is_purchase, batch_id, gold_loaded_at"
)


def build_gold_sql() -> str:
    """Return the full multi-statement Gold build script (no parameters)."""

    silver = silver_table_id()
    dim_date = gold_table_id(DIM_DATE)
    dim_category = gold_table_id(DIM_CATEGORY)
    bridge = gold_table_id(BRIDGE_CATEGORY)
    dim_brand = gold_table_id(DIM_BRAND)
    dim_product = gold_table_id(DIM_PRODUCT)
    dim_session = gold_table_id(DIM_SESSION)
    fact = gold_table_id(FACT_EVENTS)

    return f"""
DECLARE fact_events_inserted INT64 DEFAULT 0;

-- 1. dim_date ---------------------------------------------------------
CREATE OR REPLACE TABLE `{dim_date}` (
{DIM_DATE_COLUMNS}
) AS
WITH bounds AS (
  SELECT DATE(MIN(event_time)) AS min_d, DATE(MAX(event_time)) AS max_d
  FROM `{silver}`
  WHERE event_time IS NOT NULL
)
SELECT
  d AS date_key,
  EXTRACT(DAY FROM d) AS day,
  EXTRACT(ISOWEEK FROM d) AS week,
  EXTRACT(MONTH FROM d) AS month,
  FORMAT_DATE('%B', d) AS month_name,
  EXTRACT(QUARTER FROM d) AS quarter,
  EXTRACT(YEAR FROM d) AS year,
  FORMAT_DATE('%A', d) AS day_of_week,
  EXTRACT(DAYOFWEEK FROM d) IN (1, 7) AS is_weekend
FROM bounds, UNNEST(GENERATE_DATE_ARRAY(bounds.min_d, bounds.max_d)) AS d;

-- 2. dim_category ----------------------------------------------------
-- Explode each distinct category_code into every prefix level, so
-- "a.b.c" contributes nodes "a", "a.b", "a.b.c". Key = hash of the full
-- path; parent = hash of the path minus its last segment.
CREATE OR REPLACE TABLE `{dim_category}` (
{DIM_CATEGORY_COLUMNS}
) AS
WITH distinct_codes AS (
  SELECT DISTINCT category_code
  FROM `{silver}`
  WHERE category_code IS NOT NULL AND category_code != ''
),
prefixes AS (
  SELECT DISTINCT
    (
      SELECT STRING_AGG(part, '.' ORDER BY off)
      FROM UNNEST(SPLIT(dc.category_code, '.')) AS part WITH OFFSET off
      WHERE off <= depth
    ) AS category_code
  FROM distinct_codes dc,
    UNNEST(GENERATE_ARRAY(
      0, ARRAY_LENGTH(SPLIT(dc.category_code, '.')) - 1)) AS depth
),
keyed AS (
  SELECT
    FARM_FINGERPRINT(category_code) AS category_key,
    ARRAY_REVERSE(SPLIT(category_code, '.'))[OFFSET(0)] AS category_name,
    category_code,
    ARRAY_LENGTH(SPLIT(category_code, '.')) AS level_number,
    CASE
      WHEN ARRAY_LENGTH(SPLIT(category_code, '.')) > 1
      THEN FARM_FINGERPRINT(REGEXP_REPLACE(category_code, r'\\.[^.]+$', ''))
      ELSE NULL
    END AS parent_category_key
  FROM prefixes
)
SELECT
  k.category_key,
  k.category_name,
  k.category_code,
  k.parent_category_key,
  k.level_number,
  NOT EXISTS (
    SELECT 1 FROM keyed child
    WHERE child.parent_category_key = k.category_key
  ) AS is_leaf
FROM keyed k
UNION ALL
SELECT -1, 'UNKNOWN', 'UNKNOWN', NULL, 0, TRUE;

-- 3. bridge_category_hierarchy -------------------------------------
CREATE OR REPLACE TABLE `{bridge}` (
{BRIDGE_CATEGORY_COLUMNS}
) AS
WITH RECURSIVE closure AS (
  SELECT
    category_key AS ancestor_category_key,
    category_key AS descendant_category_key,
    0 AS hierarchy_level
  FROM `{dim_category}`
  UNION ALL
  SELECT
    c.ancestor_category_key,
    d.category_key AS descendant_category_key,
    c.hierarchy_level + 1
  FROM closure c
  JOIN `{dim_category}` d
    ON d.parent_category_key = c.descendant_category_key
)
SELECT ancestor_category_key, descendant_category_key, hierarchy_level
FROM closure;

-- 4. dim_brand ----------------------------------------------------
CREATE OR REPLACE TABLE `{dim_brand}` (
{DIM_BRAND_COLUMNS}
) AS
SELECT FARM_FINGERPRINT(brand) AS brand_key, brand
FROM (
  SELECT DISTINCT brand
  FROM `{silver}`
  WHERE brand IS NOT NULL AND brand != ''
)
UNION ALL
SELECT -1, 'UNKNOWN';

-- 5. dim_product (SCD1) ----------------------------------------
-- Consolidate multiple events per product_id, preferring a NON-NULL
-- category_code / brand from anywhere in the group over an arbitrary row.
CREATE OR REPLACE TABLE `{dim_product}` (
{DIM_PRODUCT_COLUMNS}
) AS
WITH consolidated AS (
  SELECT
    product_id,
    ANY_VALUE(category_code
      HAVING MAX IF(category_code IS NOT NULL, 1, 0)) AS category_code,
    ANY_VALUE(brand
      HAVING MAX IF(brand IS NOT NULL, 1, 0)) AS brand
  FROM `{silver}`
  WHERE product_id IS NOT NULL
  GROUP BY product_id
)
SELECT
  FARM_FINGERPRINT(CAST(c.product_id AS STRING)) AS product_key,
  c.product_id,
  COALESCE(dc.category_key, -1) AS category_key,
  COALESCE(db.brand_key, -1) AS brand_key
FROM consolidated c
LEFT JOIN `{dim_category}` dc ON dc.category_code = c.category_code
LEFT JOIN `{dim_brand}` db ON db.brand = c.brand;

-- 6. dim_session -------------------------------------------------
CREATE OR REPLACE TABLE `{dim_session}` (
{DIM_SESSION_COLUMNS}
) AS
SELECT
  FARM_FINGERPRINT(user_session) AS session_key,
  user_session,
  MIN(event_time) AS session_start_time,
  MAX(event_time) AS session_end_time,
  COUNT(*) AS event_count,
  COUNTIF(event_type = 'purchase') > 0 AS has_purchase,
  COUNT(DISTINCT user_id) > 1 AS is_multi_user
FROM `{silver}`
WHERE user_session IS NOT NULL AND user_session != ''
GROUP BY user_session;

-- 7. fact_events (idempotent MERGE on event_key) --------------
MERGE `{fact}` T
USING (
  SELECT
    CAST(s.surrogate_key AS STRING) AS event_key,
    s.event_time,
    DATE(s.event_time) AS date_key,
    s.event_type,
    FARM_FINGERPRINT(CAST(s.product_id AS STRING)) AS product_key,
    COALESCE(dc.category_key, -1) AS category_key,
    COALESCE(db.brand_key, -1) AS brand_key,
    FARM_FINGERPRINT(s.user_session) AS session_key,
    s.user_id,
    s.category_id,
    CAST(s.price AS FLOAT64) AS price,
    1 AS event_count,
    IF(s.event_type = 'view', 1, 0) AS is_view,
    IF(s.event_type = 'cart', 1, 0) AS is_cart,
    IF(s.event_type = 'purchase', 1, 0) AS is_purchase,
    s.batch_id,
    CURRENT_TIMESTAMP() AS gold_loaded_at
  FROM `{silver}` s
  LEFT JOIN `{dim_category}` dc ON dc.category_code = s.category_code
  LEFT JOIN `{dim_brand}` db ON db.brand = s.brand
  WHERE s.event_type IN ('view', 'cart', 'purchase')
) S
ON T.event_key = S.event_key
WHEN NOT MATCHED THEN INSERT ({_FACT_INSERT_COLUMNS})
VALUES (
  S.event_key, S.event_time, S.date_key, S.event_type, S.product_key,
  S.category_key, S.brand_key, S.session_key, S.user_id, S.category_id,
  S.price, S.event_count, S.is_view, S.is_cart, S.is_purchase, S.batch_id,
  S.gold_loaded_at
);

SET fact_events_inserted = @@row_count;

-- 8. run metrics + integrity checks (one row) ---------------
SELECT
  (SELECT COUNT(*) FROM `{silver}`)        AS silver_rows,
  (SELECT COUNT(*) FROM `{dim_date}`)      AS dim_date_rows,
  (SELECT COUNT(*) FROM `{dim_category}`)  AS dim_category_rows,
  (SELECT COUNT(*) FROM `{bridge}`)        AS bridge_category_hierarchy_rows,
  (SELECT COUNT(*) FROM `{dim_brand}`)     AS dim_brand_rows,
  (SELECT COUNT(*) FROM `{dim_product}`)   AS dim_product_rows,
  (SELECT COUNT(*) FROM `{dim_session}`)   AS dim_session_rows,
  fact_events_inserted                     AS fact_events_inserted,
  (SELECT COUNT(*) FROM `{fact}`)          AS fact_events_total,
  (
    SELECT COUNT(*) FROM `{fact}` f
    WHERE NOT EXISTS (SELECT 1 FROM `{dim_product}` d
                      WHERE d.product_key = f.product_key)
       OR NOT EXISTS (SELECT 1 FROM `{dim_category}` d
                      WHERE d.category_key = f.category_key)
       OR NOT EXISTS (SELECT 1 FROM `{dim_brand}` d
                      WHERE d.brand_key = f.brand_key)
       OR NOT EXISTS (SELECT 1 FROM `{dim_session}` d
                      WHERE d.session_key = f.session_key)
  )                                        AS fk_resolution_failures,
  (
    SELECT COUNT(*) - COUNT(DISTINCT event_key) FROM `{fact}`
  )                                        AS duplicate_event_keys;
""".strip()
