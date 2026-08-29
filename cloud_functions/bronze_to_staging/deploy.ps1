# =============================================================================
# Deploy the bronze_to_staging Cloud Function (Gen 2).
#
# Run from anywhere - the script cd's into its own folder so the --source
# upload always contains main.py + the new modules + requirements.txt.
#
#   powershell -ExecutionPolicy Bypass -File .\deploy.ps1
#
# This function is triggered by the Pub/Sub topic that gcs_to_bronze
# publishes to, so there is no bucket trigger here. First deploy in a
# fresh project: run the one-off PREREQUISITES block at the bottom.
# =============================================================================

$ErrorActionPreference = "Stop"

# --- Settings (match Terraform + config.py) -------------------------------
$Project        = "shop-sense-project"
$Region         = "asia-south1"
$Topic          = "shopsense-bronze-loaded"     # gcs_to_bronze publishes here
$OutTopic       = "shopsense-staging-loaded"    # STAGING_LOADED_TOPIC in config.py
$Runtime        = "python312"
$EntryPoint     = "bronze_to_staging"           # the @cloud_event function

# Deployed resource name (no underscores allowed). Must match the existing
# function or you create a duplicate. Check: gcloud functions list --project $Project
$FunctionName   = "bronze-to-staging"

# Runtime identity (Terraform: modules/service_account).
$ServiceAccount = "shopsense-data-pipeline-sa@$Project.iam.gserviceaccount.com"

# --- Always upload this folder -------------------------------------------
Set-Location -Path $PSScriptRoot
Write-Host "Deploying from: $PSScriptRoot" -ForegroundColor Cyan
Get-ChildItem -Name *.py, requirements.txt

gcloud config set project $Project | Out-Null

# --- Make sure the downstream topic exists ------------------------------
# This function publishes to $OutTopic at the end of a successful run.
# These setup calls are best-effort and idempotent, so drop out of "Stop"
# mode around them - otherwise "already exists" aborts the whole script.
$ErrorActionPreference = "Continue"
Write-Host "Ensuring Pub/Sub topic $OutTopic exists..." -ForegroundColor Cyan
gcloud pubsub topics create $OutTopic --project=$Project 2>&1 | Out-Null
gcloud pubsub topics add-iam-policy-binding $OutTopic --project=$Project `
  --member="serviceAccount:$ServiceAccount" `
  --role="roles/pubsub.publisher" 2>&1 | Out-Null
$ErrorActionPreference = "Stop"

# --- Deploy -----------------------------------------------------------
# --trigger-topic : run once per message published to the topic. Gen2
#   wraps this in an Eventarc/Pub-Sub push subscription automatically.
# --retry : the function now ends by publishing to $OutTopic to trigger
#   staging_to_silver. If that publish fails, we want Pub/Sub to redeliver;
#   on redelivery the already-SUCCESS batch re-sends the announcement
#   (step 3) without re-loading staging, so redelivery is safe.
gcloud functions deploy $FunctionName `
  --gen2 `
  --project=$Project `
  --region=$Region `
  --runtime=$Runtime `
  --source=. `
  --entry-point=$EntryPoint `
  --trigger-topic=$Topic `
  --retry `
  --service-account=$ServiceAccount `
  --trigger-service-account=$ServiceAccount `
  --memory=512MiB `
  --timeout=120s `
  --max-instances=12

Write-Host ""
Write-Host "Deployed. Recent logs:" -ForegroundColor Green
gcloud functions logs read $FunctionName --gen2 --region=$Region --limit=20


# =============================================================================
# PREREQUISITES  (one-off per project - safe to re-run, comment back in)
# =============================================================================
#
# # 1. APIs (same set as the other function).
# gcloud services enable `
#   run.googleapis.com cloudfunctions.googleapis.com cloudbuild.googleapis.com `
#   eventarc.googleapis.com pubsub.googleapis.com artifactregistry.googleapis.com `
#   --project=$Project
#
# # 2. Runtime service account - what this function's code actually does:
# #    - load CSV from GCS into a temp table, INSERT..SELECT into staging,
# #      and run DML on ingestion_control  -> bigquery.dataEditor + jobUser
# #    - re-check the GCS object generation -> storage.objectViewer
# #    - publish the "staging loaded" message -> pubsub.publisher
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/bigquery.dataEditor"
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/bigquery.jobUser"
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/storage.objectViewer"
#
# # 2b. Create the downstream topic and let this function publish to it.
# gcloud pubsub topics create $OutTopic --project=$Project
# gcloud pubsub topics add-iam-policy-binding $OutTopic --project=$Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/pubsub.publisher"
#
# # 3. Let the service account be invoked by the Pub/Sub push subscription
# #    and receive Eventarc events.
# $ProjectNumber = gcloud projects describe $Project --format="value(projectNumber)"
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ProjectNumber-compute@developer.gserviceaccount.com" `
#   --role="roles/eventarc.eventReceiver"
#
# # 4. The ingestion_control table must exist with these columns
# #    (batch_id STRING, bucket_name STRING, file_name STRING,
# #     generation STRING, load_type STRING, status STRING,
# #     ingestion_timestamp TIMESTAMP). Create it if Terraform hasn't:
# bq mk --table `
#   "$Project`:shopsense_analytics.ingestion_control" `
#   batch_id:STRING,bucket_name:STRING,file_name:STRING,generation:STRING,load_type:STRING,status:STRING,ingestion_timestamp:TIMESTAMP
#
# =============================================================================
# TEST  (after deploy)
# =============================================================================
#
# # This function runs automatically whenever gcs_to_bronze publishes a
# # message, so the end-to-end test is just uploading a CSV upstream:
# gcloud storage cp ..\gcs_to_bronze\sample_incremental.csv `
#   gs://shopsense-data-lake/incremental/test_001.csv
#
# gcloud functions logs read $FunctionName --gen2 --region=$Region --limit=50
#
# # Rows should appear in staging, tagged with the batch:
# bq query --use_legacy_sql=false `
#   "SELECT batch_id, load_type, COUNT(*) rows FROM \`$Project.shopsense_analytics.shopsense_raw_stg\` GROUP BY 1,2 ORDER BY 1 DESC LIMIT 5"
#
# # And the control row should read SUCCESS:
# bq query --use_legacy_sql=false `
#   "SELECT batch_id, status, ingestion_timestamp FROM \`$Project.shopsense_analytics.ingestion_control\` ORDER BY ingestion_timestamp DESC LIMIT 5"
#
# # To re-trigger this function alone (without re-uploading), publish a
# # message by hand - it must carry the same fields gcs_to_bronze sends:
# gcloud pubsub topics publish $Topic --project=$Project --message=`
#   '{\"bucket_name\":\"shopsense-data-lake\",\"file_name\":\"incremental/test_001.csv\",\"generation\":\"<GEN>\",\"batch_id\":\"BATCH_<GEN>\",\"load_type\":\"INCREMENTAL\",\"row_count\":5}'
# =============================================================================
