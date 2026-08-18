"""
runner.py — CLI entry point for the Retention Detail Report.

Usage:
    python reports/retention_detail/runner.py --bill-month 2 --fy-start 2025
    python reports/retention_detail/runner.py --bill-month 2 --fy-start 2025 --dry-run

Output:
    data/output/Retention_Detail_Report_BM<N>_<YYYY-MM>.xlsx  (local)
    SharePoint: Reports/Retention Detail Report/Output/<YYYY-MM-DD>/...  (if connected)

Run from wha-data-platform/ root, not from this folder:
    PYTHONPATH="$PWD" python3 reports/retention_detail/runner.py ...
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from src.slx.client import SLXClient
from src.hub.datahub import DataHub
from reports.retention_detail.data import collect_drilldown
from reports.retention_detail.writer import write_drilldown

REPORT_NAME     = "Retention Detail Report"
OUTPUT_DIR      = PROJECT_ROOT / "data" / "output"
TERRITORY_MAP   = PROJECT_ROOT / "config" / "territory_map.yaml"


def parse_args():
    p = argparse.ArgumentParser(
        description="WHA Retention Detail Report — unpaid members with collection notes."
    )
    p.add_argument("--bill-month", type=int, required=True, metavar="N",
                   help="Bill month (1-12). Members in cMemberGens.Duesbillmonth=N.")
    p.add_argument("--fy-start", type=int, required=True, metavar="YEAR",
                   help="Calendar year FY begins (e.g. 2025 for FY 2025-26).")
    p.add_argument("--username", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="Collect data and print summary without writing the xlsx.")
    p.add_argument("--request-delay", type=float, default=0.15, metavar="SEC")
    return p.parse_args()


def main():
    args = parse_args()

    username = args.username or os.environ.get("SLX_USERNAME")
    password = args.password or os.environ.get("SLX_PASSWORD")
    if not username or not password:
        sys.exit("ERROR: SLX credentials required (--username/--password or SLX_USERNAME/SLX_PASSWORD env).")

    # Load territory config
    cfg = yaml.safe_load(TERRITORY_MAP.read_text())
    territory_user_map = {
        uid: t for uid, t in cfg["slx_user_to_territory"].items() if t
    }
    # Rep name map: territory → first name (Amy, Bailey, ...) from rep_to_territory
    rep_name_map = {}
    for rep, raw_t in cfg.get("rep_to_territory", {}).items():
        aliases = cfg.get("aliases", {})
        canonical = aliases.get(raw_t, raw_t)
        if canonical:
            rep_name_map[canonical] = rep

    fy_label = f"{args.fy_start}-{str(args.fy_start + 1)[-2:]}"
    bm = args.bill_month

    print(f"Retention Detail Report — Bill Month {bm}, FY {fy_label}", flush=True)
    print(f"Connecting to SLX as {username}...", flush=True)

    client = SLXClient(username=username, password=password)
    print("  ✓ Connected", flush=True)
    print(f"Pulling data for {len(territory_user_map)} territories...", flush=True)

    drilldown = collect_drilldown(
        client=client,
        territory_user_map=territory_user_map,
        rep_name_map=rep_name_map,
        bill_month=bm,
        fiscal_year_start=args.fy_start,
        request_delay=args.request_delay,
    )

    # Quick summary
    total_billed = sum(s["summary"]["billed_total"] for s in drilldown.values())
    total_paid   = sum(s["summary"]["paid_total"]   for s in drilldown.values())
    total_unpaid = sum(1 for s in drilldown.values()
                       for r in s["rows"] if r["balance"] > 0)
    print(f"\nStatewide BM {bm}:", flush=True)
    print(f"  Billed:  ${total_billed:>12,.2f}", flush=True)
    print(f"  Paid:    ${total_paid:>12,.2f}", flush=True)
    print(f"  Unpaid members: {total_unpaid}", flush=True)
    if total_billed:
        print(f"  Collection rate: {total_paid/total_billed:.1%}", flush=True)

    if args.dry_run:
        print("\n[dry-run] Skipping xlsx write.", flush=True)
        return

    # Write the report
    filename = f"Retention_Detail_Report_BM{bm}_{args.fy_start}-{str(args.fy_start+1)[-2:]}.xlsx"
    local_path = OUTPUT_DIR / filename
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    write_drilldown(drilldown, local_path, bill_month=bm, fiscal_year_label=fy_label)
    print(f"\nOUTPUT:{local_path}", flush=True)
    print(f"✓ {local_path} ({local_path.stat().st_size:,} bytes)", flush=True)

    # Publish to SharePoint if connected
    hub = DataHub.connect(require_sharepoint=False)
    if hub.sharepoint_connected:
        try:
            hub.publish_report_versioned(
                report_name=REPORT_NAME,
                filename=filename,
                data=local_path.read_bytes(),
                dated=True,
            )
            print(f"✓ Pushed to SharePoint: Reports/{REPORT_NAME}/Output/<date>/{filename}",
                  flush=True)
        except Exception as exc:
            print(f"⚠ SharePoint upload failed ({exc}). Local copy still available.",
                  flush=True)
    else:
        print("  (SharePoint not connected — local copy only)", flush=True)


if __name__ == "__main__":
    main()
