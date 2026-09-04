"""
Builds the one BigQuery script that does all of the Silver work.

Everything heavy - cleaning, timestamp parsing, hashing, exact-duplicate
removal, quarantine, the surrogate-key assignment and the MERGE - runs
inside BigQuery. The Cloud Function only submits this text and reads back
a single row of counts. Nothing is ever pulled into Python memory.

Shape of the script:

    1. _batch_clean  - one pass over the staging rows for this batch:
       trim/normalise every column, SAFE-parse the timestamp, cast price
       to NUMERIC, tag each row with a reject_reason (or NULL), and
       compute row_hash over the cleaned business columns.

    2. _batch_ready  - the survivors (reject_reason IS NULL), numbered
       within each row_hash so we can tell the first copy from the
       exact-duplicate copies.

    3. _batch_new    - the deduplicated survivors whose row_hash is not
       already in Silver, each given a surrogate_key continuing from the
       current MAX(surrogate_key).

    4. BEGIN TRANSACTION
         - INSERT the rejected rows and the surplus duplicate copies into
           the quarantine table, verbatim, with a reason
         - MERGE _batch_new into Silver
       COMMIT TRANSACTION

    5. SELECT the run metrics (one row).

Idempotency:
  * A batch that already succeeded is stopped in main.py before we get
    here (ingestion_transform_control).
  * A batch that failed rolled its transaction back - BigQuery discards
    an open transaction when the script errors - so Silver and quarantine
    are untouched and a retry starts clean.
  * Even so, the MERGE only inserts row_hash values Silver does not
    already have, so re-running can never create a duplicate Silver row.

The temp tables are created outside the transaction (BigQuery does not
allow DDL inside one) and are dropped automatically when the job ends.
"""

from config import quarantine_table_id, silver_table_id, staging_table_id
from schemas import ROW_HASH_COLUMNS

# --- How each Silver column is derived from the raw staging column -------
# Columns with a real transformation get a `c_<name>` alias in
# _batch_clean; the plain INT64 ids pass straight through.
_TRANSFORMED = {
    "event_time": "SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S %Z', TRIM(src_event_time))",
    "event_type": "LOWER(TRIM(src_event_type))",
    "category_code": "NULLIF(TRIM(src_category_code), '')",
    "brand": "NULLIF(TRIM(src_brand), '')",
    "price": "CAST(src_price AS NUMERIC)",
    "user_session": "NULLIF(TRIM(src_user_session), '')",
}


def _clean_ref(name: str) -> str:
    """The _batch_clean column that holds the cleaned value for `name`."""
    return f"c_{name}" if name in _TRANSFORMED else name


# Raw staging columns preserved verbatim into quarantine, in source order.
_RAW_QUARANTINE_COLUMNS = (
    "src_event_time AS event_time",
    "src_event_type AS event_type",
    "product_id",
    "category_id",
    "src_category_code AS category_code",
    "src_brand AS brand",
    "src_price AS price",
    "user_id",
    "src_user_session AS user_session",
    "ingestion_timestamp",
    "source_file_name",
    "batch_id",
    "load_type",
)

_QUARANTINE_INSERT_COLUMNS = (
    "event_time, event_type, product_id, category_id, category_code, brand, "
    "price, user_id, user_session, ingestion_timestamp, source_file_name, "
    "batch_id, load_type, quarantine_reason, quarantined_at"
)

_SILVER_INSERT_COLUMNS = (
    "surrogate_key, row_hash, event_time, event_type, product_id, "
    "category_id, category_code, brand, price, user_id, user_session, "
    "batch_id, silver_loaded_at"
)

_SEP = ",\n    "


def build_transform_sql() -> str:
    """Return the full multi-statement Silver script (parameterised)."""

    staging = staging_table_id()
    silver = silver_table_id()
    quarantine = quarantine_table_id()

    cleaned_select = _SEP.join(
        f"{expr} AS c_{name}" for name, expr in _TRANSFORMED.items()
    )
    hash_struct_fields = _SEP.join(
        f"{_clean_ref(name)} AS {name}" for name in ROW_HASH_COLUMNS
    )
    silver_payload = _SEP.join(
        f"s.{_clean_ref(name)} AS {name}" if name in _TRANSFORMED
        else f"s.{name}"
        for name in ROW_HASH_COLUMNS
    )
    raw_quarantine_select = _SEP.join(_RAW_QUARANTINE_COLUMNS)

    return f"""
DECLARE rows_inserted INT64 DEFAULT 0;

-- 1. Clean + tag + hash every row of this batch -------------------------
CREATE TEMP TABLE _batch_clean AS
WITH src AS (
  SELECT
    event_time    AS src_event_time,
    event_type    AS src_event_type,
    product_id,
    category_id,
    category_code AS src_category_code,
    brand         AS src_brand,
    price         AS src_price,
    user_id,
    user_session  AS src_user_session,
    ingestion_timestamp,
    source_file_name,
    batch_id,
    load_type
  FROM `{staging}`
  WHERE batch_id = @batch_id
),
cleaned AS (
  SELECT
    src.*,
    {cleaned_select}
  FROM src
),
tagged AS (
  SELECT
    cleaned.*,
    CASE
      WHEN c_user_session IS NULL THEN 'SESSION_MISSING'
      WHEN c_price = 0 THEN 'PRICE_ZERO'
      WHEN src_event_time IS NOT NULL
           AND TRIM(src_event_time) != ''
           AND c_event_time IS NULL THEN 'INVALID_TIMESTAMP'
      ELSE NULL
    END AS reject_reason
  FROM cleaned
)
SELECT
  tagged.*,
  TO_HEX(SHA256(TO_JSON_STRING(STRUCT(
    {hash_struct_fields}
  )))) AS row_hash
FROM tagged;

-- 2. Survivors, numbered so we can spot exact-duplicate copies ----------
CREATE TEMP TABLE _batch_ready AS
SELECT
  *,
  ROW_NUMBER() OVER (PARTITION BY row_hash ORDER BY row_hash) AS dup_rn
FROM _batch_clean
WHERE reject_reason IS NULL;

-- 3. New Silver rows: deduped, not already present, keyed --------------
CREATE TEMP TABLE _batch_new AS
SELECT
  s.row_hash,
  {silver_payload},
  s.batch_id,
  @loaded_at AS silver_loaded_at,
  (SELECT IFNULL(MAX(surrogate_key), 0) FROM `{silver}`)
    + ROW_NUMBER() OVER (ORDER BY s.row_hash) AS surrogate_key
FROM _batch_ready s
WHERE s.dup_rn = 1
  AND NOT EXISTS (
    SELECT 1 FROM `{silver}` t WHERE t.row_hash = s.row_hash
  );

-- 4. Atomically publish quarantine + Silver ---------------------------
BEGIN TRANSACTION;

INSERT INTO `{quarantine}` ({_QUARANTINE_INSERT_COLUMNS})
SELECT
  {raw_quarantine_select},
  reject_reason AS quarantine_reason,
  @loaded_at    AS quarantined_at
FROM _batch_clean
WHERE reject_reason IS NOT NULL
UNION ALL
SELECT
  {raw_quarantine_select},
  'EXACT_DUPLICATE' AS quarantine_reason,
  @loaded_at        AS quarantined_at
FROM _batch_ready
WHERE dup_rn > 1;

MERGE `{silver}` T
USING _batch_new S
ON T.row_hash = S.row_hash
WHEN NOT MATCHED THEN INSERT ({_SILVER_INSERT_COLUMNS})
VALUES (
  S.surrogate_key, S.row_hash, S.event_time, S.event_type, S.product_id,
  S.category_id, S.category_code, S.brand, S.price, S.user_id,
  S.user_session, S.batch_id, S.silver_loaded_at
);

SET rows_inserted = @@row_count;

COMMIT TRANSACTION;

-- 5. Run metrics (one row) -------------------------------------------
SELECT
  (SELECT COUNT(*) FROM _batch_clean) AS source_rows,
  (SELECT COUNTIF(reject_reason = 'PRICE_ZERO') FROM _batch_clean)
    AS price_zero_removed,
  (SELECT COUNTIF(reject_reason = 'SESSION_MISSING') FROM _batch_clean)
    AS session_missing_removed,
  (SELECT COUNTIF(reject_reason = 'INVALID_TIMESTAMP') FROM _batch_clean)
    AS invalid_timestamp_rows,
  (SELECT COUNTIF(dup_rn > 1) FROM _batch_ready) AS exact_duplicates_removed,
  (SELECT COUNTIF(dup_rn = 1) FROM _batch_ready) AS merge_candidates,
  rows_inserted AS rows_inserted;
""".strip()
