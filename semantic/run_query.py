"""
Ad-hoc runner: compile a semantic-layer request and (optionally) run it on
BigQuery. Handy for validating the layer end to end and for debugging what the
agent's tools will send.

    # print the SQL only
    python semantic/run_query.py --metrics revenue,purchases --dimensions category_l1 --sql-only

    # run it (needs google-cloud-bigquery + application-default credentials)
    python semantic/run_query.py --metrics revenue,conversion_rate --dimensions category --order-by revenue --limit 10

    # the three MVP questions
    python semantic/run_query.py --metrics view_to_cart_dropoff,views,carts --dimensions category \\
        --filters '[{"field":"event_date","op":"last_n_days","value":7}]' --order-by view_to_cart_dropoff
    python semantic/run_query.py --segment high_intent_never_purchase --limit 5
    python semantic/run_query.py --metrics views,carts,purchases,view_to_cart_rate,cart_to_purchase_rate \\
        --dimensions category_l1 --filters '[{"field":"category_l1","op":"in","value":["electronics","apparel"]}]'
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from semantic import SemanticLayer  # noqa: E402


def _build(sl: SemanticLayer, args: argparse.Namespace):
    if args.segment:
        return sl.build_segment_query(args.segment, limit=args.limit)
    if not args.metrics:
        raise SystemExit("give --metrics or --segment")
    return sl.build_aggregate_query(
        metrics=[m.strip() for m in args.metrics.split(",") if m.strip()],
        dimensions=[d.strip() for d in args.dimensions.split(",") if d.strip()],
        filters=json.loads(args.filters) if args.filters else None,
        time_grain=args.time_grain or None,
        order_by=args.order_by or None,
        descending=not args.asc,
        limit=args.limit,
    )


def _run(compiled, project: str, location: str) -> None:
    from google.cloud import bigquery

    params = []
    for p in compiled.parameters:
        if p["type"].startswith("ARRAY<"):
            params.append(
                bigquery.ArrayQueryParameter(
                    p["name"], p["type"][len("ARRAY<") : -1], p["value"]
                )
            )
        else:
            params.append(
                bigquery.ScalarQueryParameter(p["name"], p["type"], p["value"])
            )
    client = bigquery.Client(project=project, location=location)
    rows = client.query(
        compiled.sql,
        job_config=bigquery.QueryJobConfig(query_parameters=params),
    ).result()
    for row in rows:
        print(dict(row))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metrics", help="comma-separated metric names")
    ap.add_argument("--dimensions", default="", help="comma-separated dimension names")
    ap.add_argument("--filters", default="", help='JSON list of {"field","op","value"}')
    ap.add_argument("--time-grain", dest="time_grain", default="", help="day|week|month|quarter")
    ap.add_argument("--order-by", dest="order_by", default="")
    ap.add_argument("--asc", action="store_true", help="sort ascending (default descending)")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--segment", default="", help="a segment name instead of metrics/dimensions")
    ap.add_argument("--project", default="shop-sense-project")
    ap.add_argument("--location", default="asia-south1")
    ap.add_argument("--sql-only", action="store_true", help="print SQL + params, do not run")
    args = ap.parse_args()

    compiled = _build(SemanticLayer.load(), args)
    print(compiled.sql)
    print("\n-- parameters:", compiled.parameters, "\n")
    if not args.sql_only:
        _run(compiled, args.project, args.location)


if __name__ == "__main__":
    main()
