resource "google_service_account" "pipeline" {
  account_id   = var.account_id
  display_name = var.display_name
  description  = var.description
}