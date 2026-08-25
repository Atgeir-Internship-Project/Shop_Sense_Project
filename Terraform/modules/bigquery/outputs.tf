output "dataset_id" {
  description = "ID of the ShopSense BigQuery dataset."
  value       = google_bigquery_dataset.analytics.dataset_id
}

output "raw_table_id" {
  description = "ID of the raw data table."
  value       = google_bigquery_table.raw_data.table_id
}

output "transform_table_id" {
  description = "ID of the transformed data table."
  value       = google_bigquery_table.transform_data.table_id
}

output "insight_table_id" {
  description = "ID of the business insights table."
  value       = google_bigquery_table.insight_data.table_id
}