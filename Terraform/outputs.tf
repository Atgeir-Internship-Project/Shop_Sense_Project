output "dataset_id" {
  description = "ID of the ShopSense analytics dataset."
  value       = module.bigquery.dataset_id
}

output "raw_table_id" {
  description = "ID of the raw data table."
  value       = module.bigquery.raw_table_id
}

output "shopsense_raw_stg_table_id" {
  description = "ID of the ShopSense raw staging table."
  value       = module.bigquery.shopsense_raw_stg_table_id
}


# ============================================================
# SILVER
# ============================================================

output "silver_dataset_id" {
  description = "ID of the ShopSense Silver dataset."
  value       = module.bigquery.silver_dataset_id
}

output "ingestion_transform_control_table_id" {
  description = "ID of the Silver ingestion transform control table."
  value       = module.bigquery.ingestion_transform_control_table_id
}

output "transform_data_table_id" {
  description = "ID of the ShopSense Silver transform table."
  value       = module.bigquery.transform_data_table_id
}

output "quarantine_data_table_id" {
  description = "ID of the ShopSense Silver quarantine table."
  value       = module.bigquery.quarantine_data_table_id
}


# ============================================================
# GOLD
# ============================================================

output "gold_dataset_id" {
  description = "ID of the ShopSense Gold dataset."
  value       = module.bigquery.gold_dataset_id
}

output "ingestion_insight_control_table_id" {
  description = "ID of the Gold ingestion insight control table."
  value       = module.bigquery.ingestion_insight_control_table_id
}

output "fact_events_table_id" {
  description = "ID of the Gold fact events table."
  value       = module.bigquery.fact_events_table_id
}

output "dim_date_table_id" {
  description = "ID of the Gold date dimension table."
  value       = module.bigquery.dim_date_table_id
}

output "dim_product_table_id" {
  description = "ID of the Gold product dimension table."
  value       = module.bigquery.dim_product_table_id
}

output "dim_brand_table_id" {
  description = "ID of the Gold brand dimension table."
  value       = module.bigquery.dim_brand_table_id
}

output "dim_category_table_id" {
  description = "ID of the Gold category dimension table."
  value       = module.bigquery.dim_category_table_id
}

output "dim_session_table_id" {
  description = "ID of the Gold session dimension table."
  value       = module.bigquery.dim_session_table_id
}

output "bridge_category_hierarchy_table_id" {
  description = "ID of the Gold category hierarchy bridge table."
  value       = module.bigquery.bridge_category_hierarchy_table_id
}