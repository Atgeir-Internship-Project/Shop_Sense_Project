# =============================================================================
# Deploy the staging_to_silver Cloud Function (Gen 2).
#
# Run from anywhere - the script cd's into its own folder so the --source
# upload always contains main.py + the modules + requirements.txt.
#
#   powershell -ExecutionPolicy Bypass -File .\deploy.ps1
#
# Triggered by the Pub/Sub topic that bronze_to_staging publishes to
# (shopsense-staging-loaded). First deploy in a fresh project: run the
# one-off PREREQUISITES block at the bottom.
# =============================================================================

$ErrorActionPreference = "Stop"

# --- Settings (match config.py + Terraform) -------------------------------
$Project        = "shop-sense-project"
$Region         = "asia-south1"
$Topic          = "shopsense-staging-loaded"    # bronze_to_staging publishes here
$OutTopic       = "shopsense-silver-loaded"     # SILVER_LOADED_TOPIC in config.py
$Runtime        = "python312"
$EntryPoint     = "staging_to_silver"           # the @cloud_event function

# Deployed resource name (no underscores allowed). Must match the existing
# function or you create a duplicate. Check: gcloud functions list --project $Project
$FunctionName   = "staging-to-silver"

# Runtime identity (Terraform: modules/service_account) - same SA as the
# other two functions.
$ServiceAccount = "shopsense-data-pipeline-sa@$Project.iam.gserviceaccount.com"

# --- Always upload this folder -------------------------------------------
Set-Location -Path $PSScriptRoot
Write-Host "Deploying from: $PSScriptRoot" -ForegroundColor Cyan
Get-ChildItem -Name *.py, requirements.txt

gcloud config set project $Project | Out-Null

# --- Make sure the trigger topic exists ---------------------------------
# --trigger-topic expects an existing topic; it does not create one.
# These setup calls are best-effort and idempotent ("already exists" is
# fine), so drop out of "Stop" mode around them or the script aborts on a
# harmless re-run.
$ErrorActionPreference = "Continue"
Write-Host "Ensuring Pub/Sub topics ($Topic, $OutTopic) exist..." -ForegroundColor Cyan
gcloud pubsub topics create $Topic --project=$Project 2>&1 | Out-Null
gcloud pubsub topics create $OutTopic --project=$Project 2>&1 | Out-Null
# This function publishes the finished batch to $OutTopic for silver_to_gold.
gcloud pubsub topics add-iam-policy-binding $OutTopic --project=$Project `
  --member="serviceAccount:$ServiceAccount" `
  --role="roles/pubsub.publisher" 2>&1 | Out-Null
$ErrorActionPreference = "Stop"

# --- Deploy -----------------------------------------------------------
# --trigger-topic : run once per message published to the topic.
# --retry : if the run fails, let Pub/Sub redeliver. The whole transform
#   is idempotent - ingestion_transform_control short-circuits an
#   already-SUCCESS batch, a failed run's transaction rolls back, and the
#   MERGE keys on row_hash - so redelivery never double-loads Silver.
# timeout 540s : the October historical batch (~42M rows) is one MERGE;
#   BigQuery does the work, the function just waits.
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
  --timeout=540s `
  --max-instances=6

# --- Let the trigger identity invoke the function ----------------------
# Gen2 delivers via a Pub/Sub push subscription that authenticates as the
# trigger service account. That SA needs run.invoker on the underlying
# Cloud Run service and eventarc.eventReceiver on the project. gcloud
# usually wires this on deploy, but not always - do it explicitly.
# Best-effort: skip if your account can't set these (ask an admin).
$ErrorActionPreference = "Continue"
Write-Host "Granting trigger identity run.invoker + eventReceiver..." -ForegroundColor Cyan
gcloud run services add-iam-policy-binding $FunctionName `
  --region=$Region --project=$Project `
  --member="serviceAccount:$ServiceAccount" `
  --role="roles/run.invoker" 2>&1 | Out-Null
gcloud projects add-iam-policy-binding $Project `
  --member="serviceAccount:$ServiceAccount" `
  --role="roles/eventarc.eventReceiver" 2>&1 | Out-Null
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Deployed. Recent logs:" -ForegroundColor Green
gcloud functions logs read $FunctionName --gen2 --region=$Region --limit=20


# =============================================================================
# PREREQUISITES  (one-off per project - safe to re-run, comment back in)
# =============================================================================
#
# # 1. APIs (same set as the other functions).
# gcloud services enable `
#   run.googleapis.com cloudfunctions.googleapis.com cloudbuild.googleapis.com `
#   eventarc.googleapis.com pubsub.googleapis.com artifactregistry.googleapis.com `
#   --project=$Project
#
# # 2. The trigger topic (bronze_to_staging's deploy.ps1 also creates it).
# gcloud pubsub topics create $Topic --project=$Project
#
# # 3. Runtime service account - what this function's code actually does:
# #    - read the Bronze staging table          -> bigquery.dataViewer (source dataset)
# #    - create/repair + MERGE the Silver tables -> bigquery.dataEditor (silver dataset)
# #    - run BigQuery jobs                       -> bigquery.jobUser (project)
# #    If the sibling functions already granted project-level dataEditor +
# #    jobUser, this SA can already do all of the above and nothing extra
# #    is needed. Scoped alternative:
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/bigquery.jobUser"
# bq add-iam-policy-binding --member="serviceAccount:$ServiceAccount" `
#   --role="roles/bigquery.dataViewer" "$Project`:shopsense_analytics"
# bq add-iam-policy-binding --member="serviceAccount:$ServiceAccount" `
#   --role="roles/bigquery.dataEditor" "$Project`:shopsense_analytics_silver"
#
# # 4. Let the SA be invoked by the Pub/Sub push subscription / Eventarc.
# $ProjectNumber = gcloud projects describe $Project --format="value(projectNumber)"
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ProjectNumber-compute@developer.gserviceaccount.com" `
#   --role="roles/eventarc.eventReceiver"
#
# # 5. The 3 Silver tables. Terraform is meant to own these; the function
# #    also self-heals (tables.py) if they are missing. To create by hand:
# bq mk --table "$Project`:shopsense_analytics_silver.transform_data_table" `
#   surrogate_key:INT64,row_hash:STRING,event_time:TIMESTAMP,event_type:STRING,product_id:INT64,category_id:INT64,category_code:STRING,brand:STRING,price:NUMERIC,user_id:INT64,user_session:STRING,batch_id:STRING,silver_loaded_at:TIMESTAMP
# bq mk --table "$Project`:shopsense_analytics_silver.quarantine_data_table" `
#   event_time:STRING,event_type:STRING,product_id:INT64,category_id:INT64,category_code:STRING,brand:STRING,price:FLOAT64,user_id:INT64,user_session:STRING,ingestion_timestamp:TIMESTAMP,source_file_name:STRING,batch_id:STRING,load_type:STRING,quarantine_reason:STRING,quarantined_at:TIMESTAMP
# bq mk --table "$Project`:shopsense_analytics_silver.ingestion_transform_control" `
#   batch_id:STRING,source_file_name:STRING,load_type:STRING,status:STRING,ingestion_timestamp:TIMESTAMP,source_rows:INT64,exact_duplicates_removed:INT64,price_zero_removed:INT64,session_missing_removed:INT64,invalid_timestamp_rows:INT64,rows_inserted:INT64,rows_skipped:INT64,bq_job_id:STRING
#
# =============================================================================
# TEST  (after deploy)
# =============================================================================
#
# # Silver runs automatically when bronze_to_staging publishes. End-to-end
# # test is just uploading a CSV at the top of the pipeline:
# gcloud storage cp .\sample_incremental.csv `
#   gs://shopsense-data-lake/incremental/test_001.csv
#
# gcloud functions logs read $FunctionName --gen2 --region=$Region --limit=50
#
# # Clean rows in Silver, tagged with the batch:
# bq query --use_legacy_sql=false `
#   "SELECT batch_id, COUNT(*) rows, MIN(surrogate_key) min_sk, MAX(surrogate_key) max_sk FROM \`$Project.shopsense_analytics_silver.transform_data_table\` GROUP BY 1 ORDER BY 1 DESC LIMIT 5"
#
# # Removed rows preserved in quarantine, by reason:
# bq query --use_legacy_sql=false `
#   "SELECT batch_id, quarantine_reason, COUNT(*) FROM \`$Project.shopsense_analytics_silver.quarantine_data_table\` GROUP BY 1,2 ORDER BY 1 DESC"
#
# # Control row + metrics:
# bq query --use_legacy_sql=false `
#   "SELECT * FROM \`$Project.shopsense_analytics_silver.ingestion_transform_control\` ORDER BY ingestion_timestamp DESC LIMIT 5"
#
# # Re-trigger Silver alone for a batch already in staging:
# gcloud pubsub topics publish $Topic --project=$Project --message=`
#   '{\"batch_id\":\"BATCH_<GEN>\",\"source_file_name\":\"incremental/test_001.csv\",\"load_type\":\"INCREMENTAL\",\"row_count\":5}'
# =============================================================================
