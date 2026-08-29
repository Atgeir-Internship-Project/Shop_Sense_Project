# ============================================================
# BRONZE
# ============================================================

output "dataset_id" {
  description = "ID of the ShopSense analytics dataset."
  value       = google_bigquery_dataset.analytics.dataset_id
}

output "raw_table_id" {
  description = "ID of the raw data table."
  value       = google_bigquery_table.raw_data.table_id
}

output "shopsense_raw_stg_table_id" {
  description = "ID of the ShopSense raw staging table."
  value       = google_bigquery_table.shopsense_raw_stg.table_id
}


# ============================================================
# SILVER
# ============================================================

output "silver_dataset_id" {
  description = "ID of the ShopSense Silver dataset."
  value       = google_bigquery_dataset.silver.dataset_id
}

output "ingestion_transform_control_table_id" {
  description = "ID of the Silver ingestion transform control table."
  value       = google_bigquery_table.ingestion_transform_control.table_id
}

output "transform_data_table_id" {
  description = "ID of the ShopSense Silver transform table."
  value       = google_bigquery_table.transform_data.table_id
}

output "quarantine_data_table_id" {
  description = "ID of the ShopSense Silver quarantine table."
  value       = google_bigquery_table.quarantine_data.table_id
}


# ============================================================
# GOLD
# ============================================================

output "gold_dataset_id" {
  description = "ID of the ShopSense Gold dataset."
  value       = google_bigquery_dataset.gold.dataset_id
}

output "ingestion_insight_control_table_id" {
  description = "ID of the Gold ingestion insight control table."
  value       = google_bigquery_table.ingestion_insight_control.table_id
}

output "fact_events_table_id" {
  description = "ID of the Gold fact events table."
  value       = google_bigquery_table.fact_events.table_id
}

output "dim_date_table_id" {
  description = "ID of the Gold date dimension table."
  value       = google_bigquery_table.dim_date.table_id
}

output "dim_product_table_id" {
  description = "ID of the Gold product dimension table."
  value       = google_bigquery_table.dim_product.table_id
}

output "dim_brand_table_id" {
  description = "ID of the Gold brand dimension table."
  value       = google_bigquery_table.dim_brand.table_id
}

output "dim_category_table_id" {
  description = "ID of the Gold category dimension table."
  value       = google_bigquery_table.dim_category.table_id
}

output "dim_session_table_id" {
  description = "ID of the Gold session dimension table."
  value       = google_bigquery_table.dim_session.table_id
}

output "bridge_category_hierarchy_table_id" {
  description = "ID of the Gold category hierarchy bridge table."
  value       = google_bigquery_table.bridge_category_hierarchy.table_id
}