resource "google_bigquery_dataset" "analytics" {
  dataset_id = var.dataset_id
  location   = var.location

  description = "ShopSense analytics dataset."
}

resource "google_bigquery_table" "raw_data" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "raw_data_table"

  deletion_protection = false
}

resource "google_bigquery_table" "transform_data" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "transform_data_table"

  deletion_protection = false
}

resource "google_bigquery_table" "insight_data" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "insight_data_table"

  deletion_protection = false
}

resource "google_bigquery_table" "shopsense_raw_stg" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "shopsense_raw_stg"

  deletion_protection = false
}