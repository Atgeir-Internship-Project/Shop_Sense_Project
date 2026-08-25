module "storage" {
  source = "./modules/storage"

  bucket_name = "shopsense-data-lake"
  location    = var.region
}

module "service_account" {
  source = "./modules/service_account"

  account_id   = "shopsense-data-pipeline-sa"
  display_name = "ShopSense Data Pipeline Service Account"
  description  = "Service account used by the ShopSense data pipeline."
}

module "bigquery" {
  source = "./modules/bigquery"

  dataset_id = "shopsense_analytics"
  location   = var.region
}