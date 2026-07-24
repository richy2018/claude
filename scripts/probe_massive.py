#!/usr/bin/env python
"""Massive.com options API capability probe (CLI).

Thin wrapper over backend/options/probe.py so the probe logic lives in the
module it gates (and can also refresh itself on startup). Runs BOTH the
snapshot-tier probe and the historical/flat-file probe, prints a report, and
persists it to the capabilities file the backend reads.

Usage:
    MASSIVE_API_KEY=... python scripts/probe_massive.py

The key comes ONLY from the environment. Never hardcode it, never commit it.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.options import probe as P
from backend.options.config import CAPABILITIES_PATH, UNDERLYING


def main():
    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        print("ERROR: set MASSIVE_API_KEY in the environment (do not hardcode it).")
        return 2

    print(f"Probing {P.MASSIVE_BASE_URL}/v3/snapshot/options/{UNDERLYING} ...")
    report = P.run_full_probe(api_key)
    print(f"HTTP {report.get('http_status')}")

    print("\n===== MASSIVE API CAPABILITY REPORT =====")
    for k in ("reachable", "open_interest", "day_volume", "implied_volatility",
              "greeks", "last_quote", "last_trade", "underlying_price"):
        print(f"  {k:<20} {'YES' if report.get(k) else 'no'}")
    print(f"  recency              {report.get('recency')}")
    print(f"  detected tier        {report.get('detected_tier')}")
    if report.get("error"):
        print(f"  error                {report['error']}")

    h = report.get("history") or {}
    print("\n----- HISTORICAL / FLAT-FILE REACH (gates §3 IV recon + §4 ΔOI backfill) -----")
    if "skipped" in h:
        print(f"  {h['skipped']}")
    else:
        for k in ("historical_aggregates", "asof_contract_listing",
                  "oi_in_history", "flat_files_accessible"):
            print(f"  {k:<24} {'YES' if h.get(k) else 'no'}")
        print(f"  history_earliest         {h.get('history_earliest')}")
        print(f"  oi_source                {h.get('oi_source')}")
        print(f"  day_aggregate_file_bytes {h.get('day_aggregate_file_bytes')}")
        print("  per-endpoint status:")
        for name, chk in (h.get("checks") or {}).items():
            if "skipped" in chk:
                print(f"    {name:<26} skipped ({chk['skipped']})")
            else:
                print(f"    {name:<26} HTTP {chk.get('http_status')}"
                      + (f"  {chk.get('snippet')}" if chk.get("snippet") else ""))
        for note in h.get("notes", []):
            print(f"  NOTE: {note}")
    print("=========================================")

    print(f"\nWrote {CAPABILITIES_PATH}")
    print("The backend gates snapshot/metrics features on this file; re-run the "
          "probe after any plan change or deploy.")
    return 0 if report.get("reachable") else 1


if __name__ == "__main__":
    sys.exit(main())
