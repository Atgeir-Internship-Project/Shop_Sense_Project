output "email" {
  description = "Email address of the ShopSense pipeline service account."
  value       = google_service_account.pipeline.email
}

output "name" {
  description = "Fully qualified resource name of the service account."
  value       = google_service_account.pipeline.name
}