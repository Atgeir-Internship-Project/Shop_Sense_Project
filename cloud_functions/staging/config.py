BUCKET_NAME = "shopsense-data-lake"

BIGQUERY_DATASET = "shopsense_analytics"

STAGING_TABLE = "shopsense_raw_stg"

INGESTION_CONTROL_TABLE = "ingestion_control"

# Pub/Sub topic we announce a finished staging load on. The downstream
# staging_to_silver function is subscribed here and picks up from this
# point, exactly the way this function is triggered by the topic that
# gcs_to_bronze publishes to.
STAGING_LOADED_TOPIC = "shopsense-staging-loaded"