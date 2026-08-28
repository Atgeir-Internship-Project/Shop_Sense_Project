output "data_lake_bucket" {
  description = "ShopSense data lake bucket."
  value       = module.storage.bucket_name
}

output "pipeline_service_account" {
  description = "ShopSense pipeline service account."
  value       = module.service_account.email
}

output "analytics_dataset" {
  description = "ShopSense analytics BigQuery dataset."
  value       = module.bigquery.dataset_id
}

output "raw_data_table" {
  description = "ShopSense raw data table."
  value       = module.bigquery.raw_table_id
}

output "dataset_id" {
  description = "ID of the ShopSense analytics dataset."
  value       = module.bigquery.dataset_id
}

output "raw_table_id" {
  description = "ID of the ShopSense raw data table."
  value       = module.bigquery.raw_table_id
}

output "shopsense_raw_stg_table_id" {
  description = "ID of the ShopSense raw staging table."
  value       = module.bigquery.shopsense_raw_stg_table_id
}

output "silver_dataset_id" {
  description = "ID of the ShopSense Silver dataset."
  value       = module.bigquery.silver_dataset_id
}

output "ingestion_transform_control_table_id" {
  description = "ID of the ingestion transform control table."
  value       = module.bigquery.ingestion_transform_control_table_id
}

output "transform_data_table_id" {
  description = "ID of the Silver transform data table."
  value       = module.bigquery.transform_data_table_id
}

output "quarantine_data_table_id" {
  description = "ID of the Silver quarantine data table."
  value       = module.bigquery.quarantine_data_table_id
}