# =============================================================================
# Deploy the gcs_to_bronze Cloud Function (Gen 2).
#
# Run this from anywhere - the script cd's into its own folder so the
# --source upload always contains main.py + the new modules + requirements.txt.
#
#   powershell -ExecutionPolicy Bypass -File .\deploy.ps1
#
# The first time you deploy in a fresh project, also run the one-off
# "PREREQUISITES" block near the bottom (APIs + IAM). After that, this
# script alone is enough to ship code changes.
# =============================================================================

$ErrorActionPreference = "Stop"

# --- Settings ---------------------------------------------------------------
# These match Terraform (terraform.tfvars + modules) and config.py.
$Project        = "shop-sense-project"
$Region         = "asia-south1"                 # same region as the bucket
$Bucket         = "shopsense-data-lake"         # BUCKET_NAME in config.py
$Topic          = "shopsense-bronze-loaded"     # PUBSUB_TOPIC in config.py
$Runtime        = "python312"
$EntryPoint     = "gcs_to_bronze"               # the @cloud_event function

# Cloud Function resource names can't contain underscores, so the deployed
# name uses hyphens. Change this if your existing function is named
# differently - deploying with the wrong name creates a second function.
$FunctionName   = "gcs-to-bronze"

# Runtime identity (created by Terraform: modules/service_account).
$ServiceAccount = "shopsense-data-pipeline-sa@$Project.iam.gserviceaccount.com"

# --- Make sure we upload this folder ---------------------------------------
Set-Location -Path $PSScriptRoot
Write-Host "Deploying from: $PSScriptRoot" -ForegroundColor Cyan
Get-ChildItem -Name *.py, requirements.txt

# --- Point gcloud at the right project ------------------------------------
gcloud config set project $Project | Out-Null

# --- Deploy --------------------------------------------------------------
# --trigger-bucket wires up an Eventarc trigger for the GCS "object
#   finalized" event on that bucket (fires on every new/overwritten object).
# --trigger-location must equal the bucket's location.
# --retry means a failed invocation is redelivered - safe here because the
#   downstream staging function is idempotent on batch_id.
gcloud functions deploy $FunctionName `
  --gen2 `
  --project=$Project `
  --region=$Region `
  --runtime=$Runtime `
  --source=. `
  --entry-point=$EntryPoint `
  --trigger-bucket=$Bucket `
  --trigger-location=$Region `
  --retry `
  --service-account=$ServiceAccount `
  --trigger-service-account=$ServiceAccount `
  --memory=512MiB `
  --timeout=540s `
  --max-instances=10

Write-Host ""
Write-Host "Deployed. Recent logs:" -ForegroundColor Green
gcloud functions logs read $FunctionName --gen2 --region=$Region --limit=20


# =============================================================================
# PREREQUISITES  (one-off per project - safe to re-run, comment back in)
# =============================================================================
#
# # 1. Enable the APIs Gen2 functions + Eventarc need.
# gcloud services enable `
#   run.googleapis.com `
#   cloudfunctions.googleapis.com `
#   cloudbuild.googleapis.com `
#   eventarc.googleapis.com `
#   pubsub.googleapis.com `
#   artifactregistry.googleapis.com `
#   --project=$Project
#
# # 2. Let the GCS service agent publish to Pub/Sub (Eventarc GCS triggers
# #    deliver via a Pub/Sub topic under the hood).
# $GcsAgent = gcloud storage service-agent --project=$Project
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$GcsAgent" `
#   --role="roles/pubsub.publisher"
#
# # 3. Give the runtime service account what the code actually uses:
# #    - load CSVs into BigQuery + run DML  -> dataEditor + jobUser
# #    - read the GCS object metadata       -> objectViewer
# #    - publish the "bronze loaded" message-> pubsub.publisher
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/bigquery.dataEditor"
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/bigquery.jobUser"
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/storage.objectViewer"
# gcloud pubsub topics add-iam-policy-binding $Topic --project=$Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/pubsub.publisher"
#
# # 4. The Eventarc trigger's own identity needs the event-receiver role.
# $ProjectNumber = gcloud projects describe $Project --format="value(projectNumber)"
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ProjectNumber-compute@developer.gserviceaccount.com" `
#   --role="roles/eventarc.eventReceiver"
#
# =============================================================================
# TEST  (after deploy)
# =============================================================================
#
# # Upload a small CSV under incremental/ (header must match the 9 columns):
# #   event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session
# gcloud storage cp .\sample_incremental.csv gs://$Bucket/incremental/test_001.csv
#
# # Watch it run:
# gcloud functions logs read $FunctionName --gen2 --region=$Region --limit=50
#
# # Confirm rows landed in Bronze:
# bq query --use_legacy_sql=false `
#   "SELECT COUNT(*) FROM \`$Project.shopsense_analytics.raw_data_table\`"
#
# # Confirm the Pub/Sub handoff fired (then the staging function should pick up):
# bq query --use_legacy_sql=false `
#   "SELECT batch_id, status, load_type FROM \`$Project.shopsense_analytics.ingestion_control\` ORDER BY ingestion_timestamp DESC LIMIT 5"
# =============================================================================
