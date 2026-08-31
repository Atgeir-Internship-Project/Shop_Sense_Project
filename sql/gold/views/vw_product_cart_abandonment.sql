-- =============================================================================
-- View: vw_product_cart_abandonment
--
-- Dashboard requirement: "Which products have the highest cart abandonment?"
--
-- IMPORTANT - metric definition, redefined due to a data gap:
-- There is no remove_from_cart event in this dataset (confirmed absent
-- during Silver profiling - event_type only ever takes view/cart/purchase).
-- A simple "carts minus purchases" was explicitly flagged as potentially
-- wrong in the requirements, so this is documented precisely:
--
--   A cart is treated as "abandoned" if it was not accompanied by a
--   purchase event for that same product:
--       abandoned_cart_count  = GREATEST(carts - purchases, 0)
--       cart_abandonment_rate = 1 - SAFE_DIVIDE(purchases, carts)
--
-- This is an AGGREGATE measure, not a specific-cart-to-specific-purchase
-- linkage - the schema has no cart/order id to tie one cart event to one
-- later purchase event. It is mathematically the complement of the
-- cart-to-purchase conversion rate used elsewhere in this project.
--
-- GREATEST(..., 0) guards against "buy now" style direct purchases that
-- skip the cart step entirely, which would otherwise make purchases > carts
-- for that product and produce a nonsensical negative abandoned count.
--
-- Products with zero carts are excluded (WHERE carts > 0) - "abandonment"
-- is not a meaningful concept for a product nobody has ever added to a
-- cart; this does not hide any product that has cart activity.
-- =============================================================================
CREATE OR REPLACE VIEW `shop-sense-project.shopsense_analytics_gold.vw_product_cart_abandonment` AS
WITH agg AS (
  SELECT
    product_key,
    SUM(is_cart) AS carts,
    SUM(is_purchase) AS purchases
  FROM `shop-sense-project.shopsense_analytics_gold.fact_events`
  GROUP BY product_key
)
SELECT
  p.product_key,
  p.product_id,
  c.category_code,
  c.category_name,
  b.brand,
  a.carts,
  a.purchases,
  GREATEST(a.carts - a.purchases, 0) AS abandoned_cart_count,
  1 - SAFE_DIVIDE(a.purchases, a.carts) AS cart_abandonment_rate
FROM agg a
JOIN `shop-sense-project.shopsense_analytics_gold.dim_product` p ON p.product_key = a.product_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_category` c ON c.category_key = p.category_key
JOIN `shop-sense-project.shopsense_analytics_gold.dim_brand` b ON b.brand_key = p.brand_key
WHERE a.carts > 0;
