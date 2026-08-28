# ============================================================
# BRONZE DATASET OUTPUT
# ============================================================

output "dataset_id" {
  description = "ID of the ShopSense analytics dataset."
  value       = google_bigquery_dataset.analytics.dataset_id
}


# ============================================================
# BRONZE TABLE OUTPUT
# ============================================================

output "raw_table_id" {
  description = "ID of the raw data table."
  value       = google_bigquery_table.raw_data.table_id
}


# ============================================================
# RAW STAGING TABLE OUTPUT
# ============================================================

output "shopsense_raw_stg_table_id" {
  description = "ID of the ShopSense raw staging table."
  value       = google_bigquery_table.shopsense_raw_stg.table_id
}


# ============================================================
# SILVER DATASET OUTPUT
# ============================================================

output "silver_dataset_id" {
  description = "ID of the ShopSense Silver dataset."
  value       = google_bigquery_dataset.silver.dataset_id
}


# ============================================================
# INGESTION TRANSFORM CONTROL OUTPUT
# ============================================================

output "ingestion_transform_control_table_id" {
  description = "ID of the ingestion transform control table."
  value       = google_bigquery_table.ingestion_transform_control.table_id
}


# ============================================================
# SILVER TRANSFORM TABLE OUTPUT
# ============================================================

output "transform_data_table_id" {
  description = "ID of the ShopSense Silver transform table."
  value       = google_bigquery_table.transform_data.table_id
}


# ============================================================
# QUARANTINE TABLE OUTPUT
# ============================================================

output "quarantine_data_table_id" {
  description = "ID of the ShopSense Silver quarantine table."
  value       = google_bigquery_table.quarantine_data.table_id
}