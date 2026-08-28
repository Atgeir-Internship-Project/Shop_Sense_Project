# ============================================================
# BRONZE / RAW DATASET
# ============================================================

resource "google_bigquery_dataset" "analytics" {
  dataset_id = var.dataset_id
  location   = var.location

  description = "ShopSense analytics dataset."
}


# ============================================================
# BRONZE RAW TABLE
# ============================================================

resource "google_bigquery_table" "raw_data" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "raw_data_table"

  deletion_protection = false
}


# ============================================================
# RAW STAGING TABLE
# ============================================================

resource "google_bigquery_table" "shopsense_raw_stg" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "shopsense_raw_stg"

  deletion_protection = false
}


# ============================================================
# SILVER DATASET
# ============================================================

resource "google_bigquery_dataset" "silver" {
  dataset_id = "shopsense_analytics_silver"
  location   = var.location

  description = "ShopSense Silver analytics dataset."
}


# ============================================================
# INGESTION TRANSFORM CONTROL TABLE
# ============================================================

resource "google_bigquery_table" "ingestion_transform_control" {
  dataset_id = google_bigquery_dataset.silver.dataset_id
  table_id   = "ingestion_transform_control"

  deletion_protection = false
}


# ============================================================
# SILVER TRANSFORM DATA TABLE
# ============================================================

resource "google_bigquery_table" "transform_data" {
  dataset_id = google_bigquery_dataset.silver.dataset_id
  table_id   = "transform_data_table"

  deletion_protection = false
}


# ============================================================
# SILVER QUARANTINE DATA TABLE
# ============================================================

resource "google_bigquery_table" "quarantine_data" {
  dataset_id = google_bigquery_dataset.silver.dataset_id
  table_id   = "quarantine_data_table"

  deletion_protection = false
}