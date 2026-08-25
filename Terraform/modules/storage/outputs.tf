output "bucket_name" {
  description = "Name of the ShopSense data lake bucket."
  value       = google_storage_bucket.data_lake.name
}

output "bucket_url" {
  description = "URL of the ShopSense data lake bucket."
  value       = google_storage_bucket.data_lake.url
}