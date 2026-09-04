# =============================================================================
# Deploy the silver_to_gold Cloud Function (Gen 2).
#
#   powershell -ExecutionPolicy Bypass -File .\deploy.ps1
#
# Triggered by the Pub/Sub topic staging_to_silver publishes to
# (shopsense-silver-loaded). Builds the whole Gold star schema in the
# shopsense_analytics_gold dataset. First deploy in a fresh project: also
# run the one-off PREREQUISITES block at the bottom.
# =============================================================================

$ErrorActionPreference = "Stop"

# --- Settings (match config.py + Terraform) -------------------------------
$Project        = "shop-sense-project"
$Region         = "asia-south1"
$Topic          = "shopsense-silver-loaded"     # staging_to_silver publishes here
$Runtime        = "python312"
$EntryPoint     = "silver_to_gold"              # the @cloud_event function
$FunctionName   = "silver-to-gold"              # no underscores in the resource name
$ServiceAccount = "shopsense-data-pipeline-sa@$Project.iam.gserviceaccount.com"

Set-Location -Path $PSScriptRoot
Write-Host "Deploying from: $PSScriptRoot" -ForegroundColor Cyan
Get-ChildItem -Name *.py, requirements.txt

gcloud config set project $Project | Out-Null

# --- Make sure the trigger topic exists ---------------------------------
# Best-effort + idempotent, so drop out of "Stop" mode around it.
$ErrorActionPreference = "Continue"
Write-Host "Ensuring Pub/Sub topic $Topic exists..." -ForegroundColor Cyan
gcloud pubsub topics create $Topic --project=$Project 2>&1 | Out-Null
$ErrorActionPreference = "Stop"

# --- Deploy -----------------------------------------------------------
# --retry : dimension rebuilds and the fact MERGE are each safe to re-run,
#   and ingestion_insight_control short-circuits an already-SUCCESS batch,
#   so Pub/Sub redelivery never corrupts or double-loads Gold.
# timeout 540s : the build is one BigQuery script; BigQuery does the work,
#   the function waits. A full 42M-row run may need this raised or the job
#   may outlive the function (the batch is still safe to retry).
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
  --max-instances=4

# --- Let the trigger identity invoke the function --------------------
# Gen2 delivers via a Pub/Sub push subscription authenticating as the
# trigger SA; it needs run.invoker on the Cloud Run service and
# eventarc.eventReceiver on the project. Best-effort (needs an admin).
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
# # 2. Runtime service account - what this function's code actually does:
# #    - read the Silver table                    -> bigquery.dataViewer (silver dataset)
# #    - CREATE OR REPLACE + MERGE the Gold tables -> bigquery.dataEditor (gold dataset)
# #    - run BigQuery jobs                         -> bigquery.jobUser (project)
# #    If the sibling functions already granted project-level dataEditor +
# #    jobUser, nothing extra is needed. Scoped alternative:
# gcloud projects add-iam-policy-binding $Project `
#   --member="serviceAccount:$ServiceAccount" --role="roles/bigquery.jobUser"
# bq add-iam-policy-binding --member="serviceAccount:$ServiceAccount" `
#   --role="roles/bigquery.dataViewer" "$Project`:shopsense_analytics_silver"
# bq add-iam-policy-binding --member="serviceAccount:$ServiceAccount" `
#   --role="roles/bigquery.dataEditor" "$Project`:shopsense_analytics_gold"
#
# =============================================================================
# TEST  (after deploy)
# =============================================================================
#
# # Gold runs automatically when staging_to_silver publishes. To fire it
# # by hand for a batch already in Silver:
# gcloud pubsub topics publish $Topic --project=$Project --message=`
#   '{\"batch_id\":\"BATCH_<GEN>\",\"source_file_name\":\"historical/2019-Oct.csv\",\"load_type\":\"HISTORICAL\"}'
#
# gcloud functions logs read $FunctionName --gen2 --region=$Region --limit=50
#
# # Row-count sanity (see validation_queries.sql for the full set):
# bq query --use_legacy_sql=false `
#   "SELECT
#      (SELECT COUNT(*) FROM \`$Project.shopsense_analytics_gold.fact_events\`) AS fact_rows,
#      (SELECT COUNT(*) FROM \`$Project.shopsense_analytics_silver.transform_data_table\`) AS silver_rows,
#      (SELECT COUNT(*) FROM \`$Project.shopsense_analytics_gold.dim_category\`) AS dim_category_rows"
#
# # Control row + metrics:
# bq query --use_legacy_sql=false `
#   "SELECT * FROM \`$Project.shopsense_analytics_gold.ingestion_insight_control\` ORDER BY ingestion_timestamp DESC LIMIT 5"
# =============================================================================
