import base64
import json
import re
from datetime import datetime, timezone

import functions_framework

from google.api_core.exceptions import NotFound
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

    # =====================================================
    # Pipeline Metadata
    # =====================================================

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
# Helper: Fully Qualified BigQuery Table ID
# =========================================================

def get_table_id(table_name):
    """
    Return fully-qualified BigQuery table ID.

    Format:

        project.dataset.table
    """

    return (
        f"shop-sense-project."
        f"{BIGQUERY_DATASET}."
        f"{table_name}"
    )


# =========================================================
# Helper: Ensure Staging Table Exists
# =========================================================

def ensure_staging_table(bq_client):
    """
    Ensure shopsense_raw_stg exists with the required schema.

    Terraform is NOT modified.

    If the table already exists:
        - Check required columns.
        - Add missing columns if necessary.

    If the table does not exist:
        - Create it using STAGING_SCHEMA.
    """

    table_id = get_table_id(STAGING_TABLE)

    try:

        table = bq_client.get_table(table_id)

        print(
            f"Staging table already exists: "
            f"{table_id}"
        )

        # -------------------------------------------------
        # Existing columns
        # -------------------------------------------------

        existing_columns = {
            field.name: field.field_type
            for field in table.schema
        }

        # -------------------------------------------------
        # Required columns
        # -------------------------------------------------

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

        # -------------------------------------------------
        # Add missing columns
        # -------------------------------------------------

        if missing_columns:

            print(
                "Missing staging columns detected:"
            )

            for column in missing_columns:

                print(
                    f"  - {column}"
                )

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
                "Missing staging columns "
                "added successfully."
            )

        else:

            print(
                "Staging table schema is "
                "already compatible."
            )

    except NotFound:

        # -------------------------------------------------
        # Table genuinely does not exist
        # -------------------------------------------------

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
            f"Created staging table: "
            f"{table_id}"
        )


# =========================================================
# Helper: Check Successful Processing
# =========================================================

def check_ingestion_status(
    bq_client,
    bucket_name,
    file_name,
    generation,
):
    """
    Check whether this exact GCS object generation
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

    results = list(
        query_job.result()
    )

    if results:

        print(
            "This exact GCS object generation "
            "has already been successfully processed."
        )

        return True

    return False


# =========================================================
# Helper: Create / Reuse PROCESSING Record
# =========================================================

def create_processing_record(
    bq_client,
    batch_id,
    bucket_name,
    file_name,
    generation,
    load_type,
    ingestion_timestamp,
):
    """
    Create a PROCESSING record.

    If an old PROCESSING record exists for the same
    batch, reuse it.

    If a FAILED record exists, change it back
    to PROCESSING.
    """

    table_id = get_table_id(
        INGESTION_CONTROL_TABLE
    )

    # -----------------------------------------------------
    # Check existing batch
    # -----------------------------------------------------

    check_query = f"""
        SELECT status
        FROM `{table_id}`
        WHERE batch_id = @batch_id
        ORDER BY ingestion_timestamp DESC
        LIMIT 1
    """

    check_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "batch_id",
                "STRING",
                batch_id,
            )
        ]
    )

    results = list(
        bq_client.query(
            check_query,
            job_config=check_config,
        ).result()
    )

    if results:

        existing_status = results[0].status

        # -------------------------------------------------
        # Already successful
        # -------------------------------------------------

        if existing_status == "SUCCESS":

            print(
                f"Batch {batch_id} already SUCCESS."
            )

            return "SUCCESS"

        # -------------------------------------------------
        # Already processing
        # -------------------------------------------------

        if existing_status == "PROCESSING":

            print(
                f"Batch {batch_id} already "
                f"PROCESSING."
            )

            print(
                "Reusing existing "
                "control record."
            )

            return "PROCESSING"

        # -------------------------------------------------
        # Retry failed batch
        # -------------------------------------------------

        if existing_status == "FAILED":

            update_query = f"""
                UPDATE `{table_id}`
                SET
                    status = 'PROCESSING',
                    ingestion_timestamp =
                        @ingestion_timestamp
                WHERE batch_id = @batch_id
            """

            update_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(
                        "ingestion_timestamp",
                        "TIMESTAMP",
                        ingestion_timestamp,
                    ),
                    bigquery.ScalarQueryParameter(
                        "batch_id",
                        "STRING",
                        batch_id,
                    ),
                ]
            )

            bq_client.query(
                update_query,
                job_config=update_config,
            ).result()

            print(
                f"Batch {batch_id} changed "
                f"FAILED → PROCESSING."
            )

            return "PROCESSING"

    # -----------------------------------------------------
    # Create new PROCESSING record
    # -----------------------------------------------------

    insert_query = f"""
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

    insert_config = bigquery.QueryJobConfig(
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

    bq_client.query(
        insert_query,
        job_config=insert_config,
    ).result()

    print(
        f"Ingestion control record created: "
        f"{batch_id} → PROCESSING"
    )

    return "PROCESSING"


# =========================================================
# Helper: Update Ingestion Status
# =========================================================

def update_control_status(
    bq_client,
    batch_id,
    status,
):
    """
    Update ingestion_control status.
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

    affected_rows = (
        query_job.num_dml_affected_rows
    )

    if affected_rows == 0:

        raise RuntimeError(
            f"No PROCESSING record found for "
            f"batch_id={batch_id}. "
            f"Could not update status to "
            f"{status}."
        )

    print(
        f"Batch {batch_id} marked as {status}."
    )


# =========================================================
# Helper: Create Temporary Table
# =========================================================

def create_temp_table(
    bq_client,
    batch_id,
):
    """
    Create a temporary BigQuery table.

    This table contains ONLY the original
    nine event columns.

    Metadata is added later while inserting
    into shopsense_raw_stg.
    """

    # -----------------------------------------------------
    # Make batch ID safe for BigQuery table name
    # -----------------------------------------------------

    safe_batch_id = re.sub(
        r"[^a-zA-Z0-9_]",
        "_",
        batch_id,
    )

    temp_table_name = (
        f"_bronze_stg_temp_{safe_batch_id}"
    )

    # IMPORTANT:
    # Fully-qualified:
    #
    # project.dataset.table
    #
    temp_table_id = (
        f"shop-sense-project."
        f"{BIGQUERY_DATASET}."
        f"{temp_table_name}"
    )

    print(
        f"Creating temporary table: "
        f"{temp_table_id}"
    )

    # -----------------------------------------------------
    # Delete old temp table if present
    # -----------------------------------------------------

    try:

        bq_client.delete_table(
            temp_table_id,
            not_found_ok=True,
        )

    except Exception as error:

        print(
            "Warning while cleaning old "
            f"temporary table: {error}"
        )

    # -----------------------------------------------------
    # Create temporary table
    # -----------------------------------------------------

    temp_table = bigquery.Table(
        temp_table_id,
        schema=STAGING_SCHEMA[:9],
    )

    bq_client.create_table(
        temp_table
    )

    print(
        f"Temporary table created: "
        f"{temp_table_id}"
    )

    return temp_table_id


# =========================================================
# Helper: Load GCS CSV → Temporary Table
# =========================================================

def load_gcs_to_temp_table(
    bq_client,
    gcs_uri,
    temp_table_id,
):
    """
    Load CSV directly from GCS into BigQuery.

    The CSV is NOT downloaded into
    Cloud Function memory.

    Therefore:

        GCS
          ↓
        BigQuery temporary table
    """

    raw_schema = STAGING_SCHEMA[:9]

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=raw_schema,
        write_disposition=(
            bigquery.WriteDisposition.WRITE_TRUNCATE
        ),
        allow_quoted_newlines=True,
    )

    print(
        f"Loading CSV directly from GCS: "
        f"{gcs_uri}"
    )

    load_job = (
        bq_client.load_table_from_uri(
            gcs_uri,
            temp_table_id,
            job_config=job_config,
        )
    )

    load_job.result()

    print(
        "GCS → temporary BigQuery "
        "table completed."
    )

    print(
        "Rows loaded into temporary table: "
        f"{load_job.output_rows}"
    )

    return load_job.output_rows


# =========================================================
# Helper: Insert Temporary → Staging
# =========================================================

def insert_into_staging(
    bq_client,
    temp_table_id,
    staging_table_id,
    ingestion_timestamp,
    source_file_name,
    batch_id,
    load_type,
):
    """
    Insert raw event data from temporary table
    into shopsense_raw_stg.

    Metadata is added here.
    """

    query = f"""
        INSERT INTO `{staging_table_id}`
        (
            event_time,
            event_type,
            product_id,
            category_id,
            category_code,
            brand,
            price,
            user_id,
            user_session,
            ingestion_timestamp,
            source_file_name,
            batch_id,
            load_type
        )

        SELECT
            event_time,
            event_type,
            product_id,
            category_id,
            category_code,
            brand,
            price,
            user_id,
            user_session,
            @ingestion_timestamp,
            @source_file_name,
            @batch_id,
            @load_type

        FROM `{temp_table_id}`
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "ingestion_timestamp",
                "TIMESTAMP",
                ingestion_timestamp,
            ),
            bigquery.ScalarQueryParameter(
                "source_file_name",
                "STRING",
                source_file_name,
            ),
            bigquery.ScalarQueryParameter(
                "batch_id",
                "STRING",
                batch_id,
            ),
            bigquery.ScalarQueryParameter(
                "load_type",
                "STRING",
                load_type,
            ),
        ]
    )

    print(
        "Inserting data into staging: "
        f"{staging_table_id}"
    )

    query_job = bq_client.query(
        query,
        job_config=job_config,
    )

    query_job.result()

    print(
        "Temporary table → staging "
        "completed."
    )


# =========================================================
# Helper: Delete Temporary Table
# =========================================================

def delete_temp_table(
    bq_client,
    temp_table_id,
):
    """
    Delete temporary table after processing.
    """

    try:

        bq_client.delete_table(
            temp_table_id,
            not_found_ok=True,
        )

        print(
            f"Temporary table deleted: "
            f"{temp_table_id}"
        )

    except Exception as error:

        print(
            "Warning: Could not delete "
            f"temporary table "
            f"{temp_table_id}: {error}"
        )


# =========================================================
# Cloud Function
# =========================================================

@functions_framework.cloud_event
def bronze_to_staging(cloud_event):
    """
    Pub/Sub → Staging

    Complete flow:

        Pub/Sub
            ↓
        Decode message
            ↓
        Extract bucket/file/generation
            ↓
        Check duplicate
            ↓
        Determine historical/incremental
            ↓
        Create PROCESSING record
            ↓
        Verify GCS generation
            ↓
        GCS CSV
            ↓
        Temporary BigQuery table
            ↓
        INSERT SELECT
            ↓
        shopsense_raw_stg
            ↓
        SUCCESS

    The CSV is never downloaded into
    Cloud Function memory.
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

    temp_table_id = None

    try:

        # =================================================
        # 1. Read Pub/Sub message
        # =================================================

        message_data = (
            cloud_event.data[
                "message"
            ]["data"]
        )

        decoded_data = (
            base64.b64decode(
                message_data
            ).decode("utf-8")
        )

        message = json.loads(
            decoded_data
        )

        print(
            f"Received Pub/Sub message: "
            f"{message}"
        )

        # =================================================
        # 2. Extract information
        # =================================================

        bucket_name = message[
            "bucket_name"
        ]

        file_name = message[
            "file_name"
        ]

        generation = str(
            message["generation"]
        )

        batch_id = message[
            "batch_id"
        ]

        # =================================================
        # 3. Validate bucket
        # =================================================

        if bucket_name != BUCKET_NAME:

            print(
                "Ignoring unexpected bucket: "
                f"{bucket_name}"
            )

            return

        # =================================================
        # 4. Validate CSV
        # =================================================

        if not file_name.lower().endswith(
            ".csv"
        ):

            print(
                "Skipping non-CSV file: "
                f"{file_name}"
            )

            return

        # =================================================
        # 5. Determine historical/incremental
        # =================================================

        if file_name.startswith(
            "historical/"
        ):

            load_type = "HISTORICAL"

        elif file_name.startswith(
            "incremental/"
        ):

            load_type = "INCREMENTAL"

        else:

            load_type = "UNKNOWN"

        print(
            f"Load type: {load_type}"
        )

        # =================================================
        # 6. Create ingestion timestamp
        # =================================================

        ingestion_timestamp = (
            datetime.now(
                timezone.utc
            )
        )

        print(
            "Ingestion timestamp: "
            f"{ingestion_timestamp}"
        )

        # =================================================
        # 7. Duplicate protection
        # =================================================

        already_processed = (
            check_ingestion_status(
                bq_client,
                bucket_name,
                file_name,
                generation,
            )
        )

        if already_processed:

            print(
                "Duplicate Pub/Sub event "
                "detected."
            )

            print(
                "Skipping Staging load."
            )

            return

        # =================================================
        # 8. Ensure staging table
        # =================================================

        ensure_staging_table(
            bq_client
        )

        # =================================================
        # 9. Create / reuse PROCESSING
        # =================================================

        processing_status = (
            create_processing_record(
                bq_client=bq_client,
                batch_id=batch_id,
                bucket_name=bucket_name,
                file_name=file_name,
                generation=generation,
                load_type=load_type,
                ingestion_timestamp=(
                    ingestion_timestamp
                ),
            )
        )

        # -------------------------------------------------
        # Already SUCCESS
        # -------------------------------------------------

        if processing_status == "SUCCESS":

            print(
                "Batch already successfully "
                "processed."
            )

            return

        # =================================================
        # 10. Verify exact GCS generation
        # =================================================

        bucket = storage_client.bucket(
            bucket_name
        )

        blob = bucket.blob(
            file_name,
            generation=int(
                generation
            ),
        )

        blob.reload()

        actual_generation = str(
            blob.generation
        )

        print(
            f"Pub/Sub generation: "
            f"{generation}"
        )

        print(
            "Current GCS generation: "
            f"{actual_generation}"
        )

        if (
            actual_generation
            != generation
        ):

            raise RuntimeError(
                "GCS object generation "
                "changed. "
                f"Expected {generation}, "
                f"found "
                f"{actual_generation}."
            )

        print(
            "Verified GCS object: "
            f"gs://{bucket_name}/"
            f"{file_name}"
        )

        print(
            f"File size: {blob.size} bytes"
        )

        # =================================================
        # 11. Create GCS URI
        # =================================================

        gcs_uri = (
            f"gs://{bucket_name}/"
            f"{file_name}"
        )

        # =================================================
        # 12. Create temporary table
        # =================================================

        temp_table_id = (
            create_temp_table(
                bq_client,
                batch_id,
            )
        )

        # =================================================
        # 13. Load GCS → temporary table
        # =================================================

        row_count = (
            load_gcs_to_temp_table(
                bq_client,
                gcs_uri,
                temp_table_id,
            )
        )

        if row_count == 0:

            raise ValueError(
                "CSV contains no data rows."
            )

        print(
            f"Raw rows loaded: {row_count}"
        )

        # =================================================
        # 14. Insert into staging
        # =================================================

        staging_table_id = (
            get_table_id(
                STAGING_TABLE
            )
        )

        insert_into_staging(
            bq_client=bq_client,
            temp_table_id=temp_table_id,
            staging_table_id=(
                staging_table_id
            ),
            ingestion_timestamp=(
                ingestion_timestamp
            ),
            source_file_name=file_name,
            batch_id=batch_id,
            load_type=load_type,
        )

        print(
            "Staging load completed "
            "successfully."
        )

        # =================================================
        # 15. Mark SUCCESS
        # =================================================

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

        # =================================================
        # Mark FAILED
        # =================================================

        if batch_id:

            try:

                update_control_status(
                    bq_client,
                    batch_id,
                    "FAILED",
                )

            except Exception as control_error:

                print(
                    "Could not update "
                    "ingestion_control "
                    f"to FAILED: "
                    f"{control_error}"
                )

        # =================================================
        # Re-raise error
        # =================================================

        raise

    finally:

        # =================================================
        # Always clean temporary table
        # =================================================

        if temp_table_id:

            delete_temp_table(
                bq_client,
                temp_table_id,
            )