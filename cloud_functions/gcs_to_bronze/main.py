import json

import functions_framework

from google.cloud import bigquery
from google.cloud import storage
from google.cloud import pubsub_v1

from config import (
    BUCKET_NAME,
    BIGQUERY_DATASET,
    BRONZE_TABLE,
    SUPPORTED_FILE_FORMAT,
    PUBSUB_TOPIC,
)


@functions_framework.cloud_event
def gcs_to_bronze(cloud_event):
    """
    GCS → BigQuery Bronze → Pub/Sub

    Triggered when a CSV file is uploaded to GCS.
    """

    # -----------------------------------------
    # 1. Get information from GCS event
    # -----------------------------------------

    data = cloud_event.data

    bucket_name = data["bucket"]
    file_name = data["name"]
    generation = str(data["generation"])

    print(
        f"New file detected: "
        f"gs://{bucket_name}/{file_name}"
    )

    print(f"GCS generation: {generation}")

    # -----------------------------------------
    # 2. Validate bucket
    # -----------------------------------------

    if bucket_name != BUCKET_NAME:
        print(
            f"Ignoring unexpected bucket: "
            f"{bucket_name}"
        )
        return

    # -----------------------------------------
    # 3. Process only CSV files
    # -----------------------------------------

    if not file_name.lower().endswith(
        SUPPORTED_FILE_FORMAT
    ):
        print(
            f"Skipping non-CSV file: {file_name}"
        )
        return

    # -----------------------------------------
    # 4. Create GCP clients
    # -----------------------------------------

    bq_client = bigquery.Client()

    storage_client = storage.Client()

    # -----------------------------------------
    # 5. Get GCS file information
    # -----------------------------------------

    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)

    blob.reload()

    print(f"File size: {blob.size} bytes")

    # -----------------------------------------
    # 6. Create GCS URI
    # -----------------------------------------

    gcs_uri = f"gs://{bucket_name}/{file_name}"

    # -----------------------------------------
    # 7. Create BigQuery table ID
    # -----------------------------------------

    table_id = (
        f"{bq_client.project}."
        f"{BIGQUERY_DATASET}."
        f"{BRONZE_TABLE}"
    )

    print(
        f"Destination: {table_id}"
    )

    # -----------------------------------------
    # 8. Define Bronze schema
    # -----------------------------------------

    schema = [
        bigquery.SchemaField(
            "event_time",
            "STRING"
        ),
        bigquery.SchemaField(
            "event_type",
            "STRING"
        ),
        bigquery.SchemaField(
            "product_id",
            "INT64"
        ),
        bigquery.SchemaField(
            "category_id",
            "INT64"
        ),
        bigquery.SchemaField(
            "category_code",
            "STRING"
        ),
        bigquery.SchemaField(
            "brand",
            "STRING"
        ),
        bigquery.SchemaField(
            "price",
            "FLOAT64"
        ),
        bigquery.SchemaField(
            "user_id",
            "INT64"
        ),
        bigquery.SchemaField(
            "user_session",
            "STRING"
        ),
    ]

    # -----------------------------------------
    # 9. Configure BigQuery load
    # -----------------------------------------

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=schema,
        write_disposition=(
            bigquery.WriteDisposition.WRITE_APPEND
        ),
    )

    # -----------------------------------------
    # 10. Load CSV → Bronze
    # -----------------------------------------

    print(
        f"Loading {gcs_uri} into Bronze..."
    )

    load_job = bq_client.load_table_from_uri(
        gcs_uri,
        table_id,
        job_config=job_config,
    )

    # Wait for BigQuery load to finish
    load_job.result()

    print(
        f"Bronze load successful."
    )

    print(
        f"Rows loaded: {load_job.output_rows}"
    )

    # -----------------------------------------
    # 11. Determine historical/incremental
    # -----------------------------------------

    if file_name.startswith("historical/"):
        load_type = "HISTORICAL"

    elif file_name.startswith("incremental/"):
        load_type = "INCREMENTAL"

    else:
        load_type = "UNKNOWN"

    print(
        f"Load type: {load_type}"
    )

    # -----------------------------------------
    # 12. Create batch ID
    # -----------------------------------------

    batch_id = f"BATCH_{generation}"

    print(
        f"Batch ID: {batch_id}"
    )

    # -----------------------------------------
    # 13. Create Pub/Sub message
    # -----------------------------------------

    message = {
        "bucket_name": bucket_name,
        "file_name": file_name,
        "generation": generation,
        "batch_id": batch_id,
        "load_type": load_type,
        "row_count": load_job.output_rows,
    }

    message_data = json.dumps(
        message
    ).encode("utf-8")

    # -----------------------------------------
    # 14. Publish Pub/Sub message
    # -----------------------------------------

    publisher = pubsub_v1.PublisherClient()

    topic_path = publisher.topic_path(
        bq_client.project,
        PUBSUB_TOPIC
    )

    print(
        f"Publishing message to: "
        f"{topic_path}"
    )

    future = publisher.publish(
        topic_path,
        message_data
    )

    message_id = future.result()

    print(
        f"Pub/Sub message published."
    )

    print(
        f"Message ID: {message_id}"
    )

    print(
        "GCS → Bronze → Pub/Sub completed successfully."
    )