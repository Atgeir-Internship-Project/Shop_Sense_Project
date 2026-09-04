"""
BigQuery schema for the Bronze table.

Bronze is the "landing zone": we keep the data exactly as it arrives in
the source CSV, with no cleaning and no extra columns. The nine fields
below match the column order of the ShopSense e-commerce event files.

Note that `event_time` is loaded as STRING on purpose - parsing it into a
real TIMESTAMP is a job for the Silver layer, not Bronze. If a row has a
malformed timestamp we still want it to land so we can inspect it later.
"""

from google.cloud import bigquery

BRONZE_SCHEMA = [
    bigquery.SchemaField("event_time", "STRING"),      # kept raw, parsed later
    bigquery.SchemaField("event_type", "STRING"),      # view / cart / purchase
    bigquery.SchemaField("product_id", "INT64"),
    bigquery.SchemaField("category_id", "INT64"),
    bigquery.SchemaField("category_code", "STRING"),   # e.g. "electronics.smartphone"
    bigquery.SchemaField("brand", "STRING"),
    bigquery.SchemaField("price", "FLOAT64"),
    bigquery.SchemaField("user_id", "INT64"),
    bigquery.SchemaField("user_session", "STRING"),    # groups events in one visit
]
