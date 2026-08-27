import base64
import csv
import io
import json
from datetime import datetime, timezone

import functions_framework

from google.cloud import bigquery
from google.cloud import storage

from config import (
    BUCKET_NAME,
    BIGQUERY_DATASET,
    STAGING_TABLE,
    INGESTION_CONTROL_TABLE,
)


# =========================================================
# BigQuery Staging Schema
# =========================================================

STAGING_SCHEMA = [
    bigquery.SchemaField(
        "event_time",
        "STRING",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "event_type",
        "STRING",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "product_id",
        "INT64",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "category_id",
        "INT64",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "category_code",
        "STRING",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "brand",
        "STRING",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "price",
        "FLOAT64",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "user_id",
        "INT64",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "user_session",
        "STRING",
        mode="NULLABLE",
    ),

    # Pipeline metadata
    bigquery.SchemaField(
        "ingestion_timestamp",
        "TIMESTAMP",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "source_file_name",
        "STRING",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "batch_id",
        "STRING",
        mode="NULLABLE",
    ),
    bigquery.SchemaField(
        "load_type",
        "STRING",
        mode="NULLABLE",
    ),
]


# =========================================================
# Helper: Get Fully Qualified Table ID
# =========================================================

def get_table_id(table_name):
    return f"{BIGQUERY_DATASET}.{table_name}"


# =========================================================
# Helper: Ensure Staging Table Exists
# =========================================================

def ensure_staging_table(bq_client):
    """
    Ensures shopsense_raw_stg exists with the required schema.

    Terraform is not modified.
    """

    table_id = get_table_id(STAGING_TABLE)

    try:
        table = bq_client.get_table(table_id)

        print(
            f"Staging table already exists: {table_id}"
        )

        existing_columns = {
            field.name: field.field_type
            for field in table.schema
        }

        required_columns = {
            field.name: field.field_type
            for field in STAGING_SCHEMA
        }

        missing_columns = []

        for column_name, column_type in required_columns.items():

            if column_name not in existing_columns:

                missing_columns.append(
                    f"{column_name} ({column_type})"
                )

        if missing_columns:

            print(
                "Missing staging columns detected:"
            )

            for column in missing_columns:
                print(f"  - {column}")

            new_schema = list(table.schema)

            for field in STAGING_SCHEMA:

                if field.name not in existing_columns:

                    new_schema.append(field)

            table.schema = new_schema

            bq_client.update_table(
                table,
                ["schema"],
            )

            print(
                "Missing columns added successfully."
            )

        else:

            print(
                "Staging table schema is already compatible."
            )

    except Exception as error:

        print(
            f"Staging table does not exist. "
            f"Creating: {table_id}"
        )

        table = bigquery.Table(
            table_id,
            schema=STAGING_SCHEMA,
        )

        bq_client.create_table(table)

        print(
            f"Created staging table: {table_id}"
        )


# =========================================================
# Helper: Check Duplicate Processing
# =========================================================

def check_ingestion_status(
    bq_client,
    bucket_name,
    file_name,
    generation,
):
    """
    Checks whether this exact GCS object generation
    has already been successfully processed.

    Duplicate identity:

        bucket_name
        +
        file_name
        +
        generation
    """

    table_id = get_table_id(
        INGESTION_CONTROL_TABLE
    )

    query = f"""
        SELECT status
        FROM `{table_id}`
        WHERE bucket_name = @bucket_name
          AND file_name = @file_name
          AND generation = @generation
          AND status = 'SUCCESS'
        ORDER BY ingestion_timestamp DESC
        LIMIT 1
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "bucket_name",
                "STRING",
                bucket_name,
            ),
            bigquery.ScalarQueryParameter(
                "file_name",
                "STRING",
                file_name,
            ),
            bigquery.ScalarQueryParameter(
                "generation",
                "STRING",
                generation,
            ),
        ]
    )

    query_job = bq_client.query(
        query,
        job_config=job_config,
    )

    results = list(query_job.result())

    if results:

        print(
            "This exact GCS object generation "
            "has already been successfully processed."
        )

        return True

    return False


# =========================================================
# Helper: Insert PROCESSING Record
# =========================================================

def insert_control_record(
    bq_client,
    batch_id,
    bucket_name,
    file_name,
    generation,
    load_type,
    ingestion_timestamp,
):
    """
    Inserts a PROCESSING record into ingestion_control.

    Uses BigQuery DML INSERT instead of insert_rows_json()
    so that the row can immediately participate in the
    subsequent UPDATE to SUCCESS or FAILED.
    """

    table_id = get_table_id(
        INGESTION_CONTROL_TABLE
    )

    query = f"""
        INSERT INTO `{table_id}`
        (
            batch_id,
            bucket_name,
            file_name,
            generation,
            load_type,
            status,
            ingestion_timestamp
        )
        VALUES
        (
            @batch_id,
            @bucket_name,
            @file_name,
            @generation,
            @load_type,
            'PROCESSING',
            @ingestion_timestamp
        )
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "batch_id",
                "STRING",
                batch_id,
            ),
            bigquery.ScalarQueryParameter(
                "bucket_name",
                "STRING",
                bucket_name,
            ),
            bigquery.ScalarQueryParameter(
                "file_name",
                "STRING",
                file_name,
            ),
            bigquery.ScalarQueryParameter(
                "generation",
                "STRING",
                generation,
            ),
            bigquery.ScalarQueryParameter(
                "load_type",
                "STRING",
                load_type,
            ),
            bigquery.ScalarQueryParameter(
                "ingestion_timestamp",
                "TIMESTAMP",
                ingestion_timestamp,
            ),
        ]
    )

    query_job = bq_client.query(
        query,
        job_config=job_config,
    )

    query_job.result()

    print(
        f"Ingestion control record created: "
        f"{batch_id} → PROCESSING"
    )


# =========================================================
# Helper: Update Ingestion Control Status
# =========================================================

def update_control_status(
    bq_client,
    batch_id,
    status,
):
    """
    Updates:

        PROCESSING → SUCCESS

    or:

        PROCESSING → FAILED
    """

    table_id = get_table_id(
        INGESTION_CONTROL_TABLE
    )

    query = f"""
        UPDATE `{table_id}`
        SET status = @status
        WHERE batch_id = @batch_id
          AND status = 'PROCESSING'
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "status",
                "STRING",
                status,
            ),
            bigquery.ScalarQueryParameter(
                "batch_id",
                "STRING",
                batch_id,
            ),
        ]
    )

    query_job = bq_client.query(
        query,
        job_config=job_config,
    )

    query_job.result()

    affected_rows = query_job.num_dml_affected_rows

    if affected_rows == 0:

        raise RuntimeError(
            f"No PROCESSING record found for "
            f"batch_id={batch_id}. "
            f"Could not update status to {status}."
        )

    print(
        f"Batch {batch_id} marked as {status}."
    )


# =========================================================
# Cloud Function
# =========================================================

@functions_framework.cloud_event
def bronze_to_staging(cloud_event):
    """
    Pub/Sub → Staging

    Flow:

    Pub/Sub
        ↓
    Decode message
        ↓
    Check duplicate
        ↓
    Determine historical/incremental
        ↓
    Create ingestion control = PROCESSING
        ↓
    Read exact GCS object
        ↓
    Add metadata
        ↓
    Load into shopsense_raw_stg
        ↓
    Update ingestion control = SUCCESS

    If anything fails:

        PROCESSING → FAILED
    """

    print(
        "=========================================="
    )

    print(
        "Bronze → Staging function started"
    )

    print(
        "=========================================="
    )

    bq_client = bigquery.Client()
    storage_client = storage.Client()

    batch_id = None

    try:

        # =====================================================
        # 1. Read Pub/Sub message
        # =====================================================

        message_data = (
            cloud_event.data["message"]["data"]
        )

        decoded_data = base64.b64decode(
            message_data
        ).decode("utf-8")

        message = json.loads(
            decoded_data
        )

        print(
            f"Received Pub/Sub message: {message}"
        )

        # =====================================================
        # 2. Extract message information
        # =====================================================

        bucket_name = message["bucket_name"]

        file_name = message["file_name"]

        generation = str(
            message["generation"]
        )

        batch_id = message["batch_id"]

        # =====================================================
        # 3. Validate bucket
        # =====================================================

        if bucket_name != BUCKET_NAME:

            print(
                f"Ignoring unexpected bucket: "
                f"{bucket_name}"
            )

            return

        # =====================================================
        # 4. Validate file
        # =====================================================

        if not file_name.lower().endswith(".csv"):

            print(
                f"Skipping non-CSV file: "
                f"{file_name}"
            )

            return

        # =====================================================
        # 5. Determine historical/incremental
        # =====================================================

        if file_name.startswith("historical/"):

            load_type = "HISTORICAL"

        elif file_name.startswith("incremental/"):

            load_type = "INCREMENTAL"

        else:

            load_type = "UNKNOWN"

        print(
            f"Load type: {load_type}"
        )

        # =====================================================
        # 6. Create ingestion timestamp
        # =====================================================

        ingestion_timestamp = datetime.now(
            timezone.utc
        )

        print(
            f"Ingestion timestamp: "
            f"{ingestion_timestamp}"
        )

        # =====================================================
        # 7. Duplicate protection
        # =====================================================

        already_processed = check_ingestion_status(
            bq_client,
            bucket_name,
            file_name,
            generation,
        )

        if already_processed:

            print(
                "Duplicate Pub/Sub event detected."
            )

            print(
                "Skipping Staging load."
            )

            return

        # =====================================================
        # 8. Ensure Staging table exists
        # =====================================================

        ensure_staging_table(
            bq_client
        )

        # =====================================================
        # 9. Create PROCESSING record
        # =====================================================

        insert_control_record(
            bq_client=bq_client,
            batch_id=batch_id,
            bucket_name=bucket_name,
            file_name=file_name,
            generation=generation,
            load_type=load_type,
            ingestion_timestamp=ingestion_timestamp,
        )

        # =====================================================
        # 10. Get exact GCS object
        # =====================================================

        bucket = storage_client.bucket(
            bucket_name
        )

        blob = bucket.blob(
            file_name,
            generation=int(generation),
        )

        print(
            "Reading exact GCS object:"
        )

        print(
            f"gs://{bucket_name}/{file_name}"
        )

        print(
            f"Generation: {generation}"
        )

        # =====================================================
        # 11. Download CSV
        # =====================================================

        csv_content = (
            blob.download_as_text()
        )

        print(
            "CSV downloaded successfully."
        )

        # =====================================================
        # 12. Read CSV
        # =====================================================

        csv_file = io.StringIO(
            csv_content
        )

        reader = csv.DictReader(
            csv_file
        )

        expected_columns = [
            "event_time",
            "event_type",
            "product_id",
            "category_id",
            "category_code",
            "brand",
            "price",
            "user_id",
            "user_session",
        ]

        if reader.fieldnames != expected_columns:

            raise ValueError(
                "CSV schema does not match expected schema.\n"
                f"Expected: {expected_columns}\n"
                f"Received: {reader.fieldnames}"
            )

        # =====================================================
        # 13. Prepare staging rows
        # =====================================================

        staging_rows = []

        row_count = 0

        for csv_row in reader:

            row_count += 1

            staging_row = {

                # -----------------------------------------
                # Original source values
                # -----------------------------------------

                "event_time": csv_row["event_time"],

                "event_type": csv_row["event_type"],

                "product_id": (
                    int(csv_row["product_id"])
                    if csv_row["product_id"]
                    else None
                ),

                "category_id": (
                    int(csv_row["category_id"])
                    if csv_row["category_id"]
                    else None
                ),

                "category_code": (
                    csv_row["category_code"]
                    if csv_row["category_code"]
                    else None
                ),

                "brand": (
                    csv_row["brand"]
                    if csv_row["brand"]
                    else None
                ),

                "price": (
                    float(csv_row["price"])
                    if csv_row["price"]
                    else None
                ),

                "user_id": (
                    int(csv_row["user_id"])
                    if csv_row["user_id"]
                    else None
                ),

                "user_session": (
                    csv_row["user_session"]
                    if csv_row["user_session"]
                    else None
                ),

                # -----------------------------------------
                # Pipeline metadata
                # -----------------------------------------

                "ingestion_timestamp": (
                    ingestion_timestamp.isoformat()
                ),

                "source_file_name": file_name,

                "batch_id": batch_id,

                "load_type": load_type,
            }

            staging_rows.append(
                staging_row
            )

        print(
            f"Rows prepared: {row_count}"
        )

        # =====================================================
        # 14. Validate CSV isn't empty
        # =====================================================

        if not staging_rows:

            raise ValueError(
                "CSV contains no data rows."
            )

        # =====================================================
        # 15. Load into Staging
        # =====================================================

        staging_table_id = get_table_id(
            STAGING_TABLE
        )

        print(
            f"Loading rows into: "
            f"{staging_table_id}"
        )

        load_job_config = (
            bigquery.LoadJobConfig(
                schema=STAGING_SCHEMA,
                write_disposition=(
                    bigquery.WriteDisposition.WRITE_APPEND
                ),
            )
        )

        load_job = (
            bq_client.load_table_from_json(
                staging_rows,
                staging_table_id,
                job_config=load_job_config,
            )
        )

        # Wait until BigQuery finishes
        load_job.result()

        print(
            "Staging load completed successfully."
        )

        print(
            f"Rows loaded into staging: "
            f"{row_count}"
        )

        # =====================================================
        # 16. Mark SUCCESS
        # =====================================================

        update_control_status(
            bq_client,
            batch_id,
            "SUCCESS",
        )

        print(
            "=========================================="
        )

        print(
            "Bronze → Staging completed successfully."
        )

        print(
            f"Rows loaded: {row_count}"
        )

        print(
            f"Batch ID: {batch_id}"
        )

        print(
            f"Load type: {load_type}"
        )

        print(
            "Ingestion control status: SUCCESS"
        )

        print(
            "=========================================="
        )

    except Exception as error:

        print(
            "=========================================="
        )

        print(
            "Bronze → Staging failed."
        )

        print(
            f"Error: {error}"
        )

        print(
            "=========================================="
        )

        # =====================================================
        # Mark FAILED
        # =====================================================

        if batch_id:

            try:

                update_control_status(
                    bq_client,
                    batch_id,
                    "FAILED",
                )

            except Exception as control_error:

                print(
                    "Could not update ingestion_control "
                    f"to FAILED: {control_error}"
                )

        # =====================================================
        # Re-raise so Cloud Functions knows execution failed
        # =====================================================

        raise