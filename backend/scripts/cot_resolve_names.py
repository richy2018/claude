#!/usr/bin/env python
"""COT pre-backfill checkpoint — resolve CONTRACTS -> verbatim CFTC names.

Run this BEFORE backfilling. It loads each report from CFTC and resolves every
friendly symbol's candidate substrings against the live available-contract list,
printing a review table (and optional JSON). Review the resolved names — any
`None` means the candidate substrings missed and the config line needs a tweak —
then run cot_backfill.py.

    python -m backend.scripts.cot_resolve_names            # table
    python -m backend.scripts.cot_resolve_names --json out.json

Requires network egress to www.cftc.gov (allowed on Render; blocked in some
sandboxes — in that case run on the deploy target).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.cot.config import CONTRACTS, CLASS_ORDER, CLASS_LABELS  # noqa: E402
from backend.cot.fetcher import resolve_all_names  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write resolved mapping to this path")
    args = ap.parse_args()

    print("Resolving contract names against live CFTC reports...\n")
    resolved = resolve_all_names()

    unresolved = []
    by_class = {}
    for sym, entry in resolved.items():
        by_class.setdefault(entry["class"], []).append((sym, entry))

    hdr = f"{'SYM':<6}{'CLASS':<11}{'PRIMARY REPORT':<20}{'RESOLVED PRIMARY':<46}{'LEGACY'}"
    print(hdr)
    print("-" * len(hdr))
    for cls in CLASS_ORDER:
        for sym, entry in by_class.get(cls, []):
            prk = entry["primary_report"]
            primary = entry.get(prk)
            legacy = entry.get("legacy_fut")
            if not primary or str(primary).startswith("<"):
                unresolved.append((sym, prk))
            if not legacy or str(legacy).startswith("<"):
                unresolved.append((sym, "legacy_fut"))
            print(f"{sym:<6}{cls:<11}{prk:<20}{str(primary):<46}{str(legacy)}")

    print(f"\nResolved {len(CONTRACTS)} symbols across "
          f"{len({c['report'] for c in CONTRACTS.values()} | {'legacy_fut'})} reports.")
    if unresolved:
        print(f"\n⚠️  {len(unresolved)} UNRESOLVED — fix CONTRACTS substrings before backfill:")
        for sym, rk in unresolved:
            print(f"    {sym} / {rk}  (candidates: {CONTRACTS[sym]['names']})")
    else:
        print("\n✅ All symbols resolved for both their primary report and legacy.")

    if args.json:
        Path(args.json).write_text(json.dumps(resolved, indent=2, default=str))
        print(f"\nWrote {args.json}")

    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
