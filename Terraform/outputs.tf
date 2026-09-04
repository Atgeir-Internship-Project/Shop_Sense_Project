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

output "transform_data_table" {
  description = "ShopSense transformed data table."
  value       = module.bigquery.transform_table_id
}

output "insight_data_table" {
  description = "ShopSense business insights table."
  value       = module.bigquery.insight_table_id
}