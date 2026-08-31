# =============================================================================
# Deploy the Gold-layer analytical views to BigQuery.
#
# Each .sql file in this folder is one standalone CREATE OR REPLACE VIEW
# statement - runnable on its own (paste into the BigQuery console, or via
# `bq query`), exactly like the reference queries in
# cloud_functions/silver_to_gold/validation_queries.sql. This script just
# runs all of them in one go, so the full set can be (re)deployed with a
# single command whenever a view's SQL changes.
#
#   powershell -ExecutionPolicy Bypass -File .\deploy_views.ps1
#
# Requires the `bq` CLI (part of the Google Cloud SDK) and to be logged in
# with an account that has bigquery.dataEditor + bigquery.jobUser on
# shop-sense-project (the same access the pipeline's own deploys rely on).
# =============================================================================

$ErrorActionPreference = "Stop"

$Project = "shop-sense-project"
$Dataset = "shopsense_analytics_gold"

Set-Location -Path $PSScriptRoot
gcloud config set project $Project | Out-Null

# vw_category_remove_cart_rate.sql is deliberately absent - see
# docs/GOLD_VIEWS.md for why (the dataset has no remove_from_cart event).
$files = Get-ChildItem -Path $PSScriptRoot -Filter "vw_*.sql" | Sort-Object Name

Write-Host "Deploying $($files.Count) views to $Project.$Dataset ..." -ForegroundColor Cyan

foreach ($file in $files) {
    Write-Host "  -> $($file.Name)" -ForegroundColor Cyan
    # Pipe the SQL in via stdin rather than passing it as a command-line
    # argument. These files are multi-line and full of "--" comments, which
    # a native .cmd wrapper like bq can mis-parse as flags once Windows'
    # argument quoting mangles a multi-line string - piping avoids that
    # entirely, since piped content is never re-parsed as arguments.
    Get-Content -Raw -Path $file.FullName | bq query --use_legacy_sql=false --project_id=$Project
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to deploy $($file.Name) - fix the error above and re-run."
    }
}

Write-Host ""
Write-Host "All views deployed." -ForegroundColor Green
bq ls --project_id=$Project $Dataset


# =============================================================================
# VALIDATE  (after deploy - see docs/GOLD_VIEWS.md for the full checklist)
# =============================================================================
#
# # Each view returns rows and compiles cleanly:
# bq query --use_legacy_sql=false --project_id=$Project `
#   "SELECT COUNT(*) FROM `$Project.$Dataset.vw_category_view_cart_dropout`"
#
# # Spot-check one view's numbers against the underlying fact table directly:
# bq query --use_legacy_sql=false --project_id=$Project `
#   "SELECT SUM(is_view) v, SUM(is_cart) c FROM `$Project.shopsense_analytics_gold.fact_events`"
# # ... then compare against: SELECT SUM(views), SUM(carts) FROM vw_category_view_cart_dropout
# =============================================================================
