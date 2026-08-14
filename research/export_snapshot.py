"""Export a full-history data snapshot for the offline bias re-test.

WHY: `/api/data/fred` serves `df.tail(2520)`, so an export taken through the API
loses everything before ~2019 and the re-test cannot build a risk-free series or
a credit component. This script pulls full history straight from the sources and
writes one self-contained file.

WHERE TO RUN: anywhere with outbound network and FRED_API_KEY set — the Render
shell is ideal, since the key is already in the environment there.

    cd ~/project/src
    python -m research.export_snapshot

Writes research/snapshot/full_snapshot.json. Commit and push it; the re-test
reads it directly and needs nothing else.

WHAT IT COLLECTS
    FRED        full history from 2000-01-01 for the series the signal uses,
                including BAA10Y (the credit spread that actually has history —
                see config.CREDIT_SPREAD_SERIES for why not HY OAS).
    SPY         daily closes, as far back as the source allows.
    BIS         all-sector and private non-financial credit, quarterly.
    xccy basis  the dollar-stress gist.

Any source that fails is recorded in the file's "errors" block rather than
aborting the run — a partial snapshot is still useful, and the gap is visible.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

START = "2000-01-01"
OUT = ROOT / "research" / "snapshot" / "full_snapshot.json"

FRED_SERIES = [
    "BAA10Y",         # credit spread WITH history — the point of this export
    "BAMLH0A0HYM2",   # HY OAS, rolling 3y only; kept for comparison
    "AAA10Y",         # second IG spread, useful as a robustness check
    "DFF", "FEDFUNDS",  # policy rate + risk-free
    "T10Y2Y",         # yield curve
    "M2SL",           # money supply
    "DGS10", "DGS2",
]

# Series to ALSO fetch as first-published values (ALFRED output_type=4).
#
# These are the ones that get revised, so the number visible today is not the
# number anyone saw at the time. Fetching the initial release recovers what was
# actually reported then, which is what a historical signal has to be built from
# if its entries and exits are to mean anything.
#
# Deliberately short: HY OAS, cross-currency basis and Fed funds are market or
# administrative data and are not restated, so their current values ARE the
# as-reported values. M2SL is restated every year when seasonal factors are
# re-estimated. BIS credit is restated and rebased too, but BIS publishes no
# vintage API, so it cannot be recovered this way — see pit_history.py.
FRED_FIRST_RELEASE = ["M2SL"]


def _series_to_records(s):
    return [{"date": i.strftime("%Y-%m-%d"), "value": None if pd.isna(v) else float(v)}
            for i, v in s.items()]


def fetch_fred(errors):
    import requests
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        errors["fred"] = "FRED_API_KEY not set in environment"
        return {}

    out = {}
    for sid in FRED_SERIES:
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": sid, "api_key": key, "file_type": "json",
                        "observation_start": START, "sort_order": "asc"},
                timeout=60,
            )
            r.raise_for_status()
            obs = r.json().get("observations", [])
            df = pd.DataFrame(obs)
            if df.empty:
                errors[f"fred:{sid}"] = "no observations returned"
                continue
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            s = df.set_index("date")["value"].dropna()
            out[sid] = _series_to_records(s)
            print(f"  [FRED] {sid:<15} {len(s):>6} obs  "
                  f"{s.index[0].date()} -> {s.index[-1].date()}")
        except Exception as e:                              # noqa: BLE001
            errors[f"fred:{sid}"] = str(e)
            print(f"  [FRED] {sid:<15} FAILED: {e}")
    return out


def fetch_fred_first_release(errors):
    """First-published value per observation date, via ALFRED output_type=4.

    This is what a real-time observer saw before any revision — the number that
    was actually reported at the time. One request per series.
    """
    import requests
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        errors["fred_first_release"] = "FRED_API_KEY not set"
        return {}

    out = {}
    for sid in FRED_FIRST_RELEASE:
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": sid, "api_key": key, "file_type": "json",
                        "observation_start": START, "sort_order": "asc",
                        "output_type": 4},          # 4 = initial release only
                timeout=60,
            )
            r.raise_for_status()
            obs = r.json().get("observations", [])
            df = pd.DataFrame(obs)
            if df.empty:
                errors[f"fred_first:{sid}"] = "no observations returned"
                continue
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            s = df.set_index("date")["value"].dropna()
            out[sid] = _series_to_records(s)
            print(f"  [PIT ] {sid:<15} {len(s):>6} first-release obs  "
                  f"{s.index[0].date()} -> {s.index[-1].date()}")
        except Exception as e:                              # noqa: BLE001
            errors[f"fred_first:{sid}"] = str(e)
            print(f"  [PIT ] {sid:<15} FAILED: {e}")
    return out


def fetch_spy(errors):
    try:
        import yfinance as yf
        df = yf.download("SPY", start="1993-01-01", progress=False, auto_adjust=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        s = df[col].dropna()
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        print(f"  [SPY]  {len(s):>6} obs  {s.index[0].date()} -> {s.index[-1].date()}")
        return _series_to_records(s)
    except Exception as e:                                  # noqa: BLE001
        errors["spy"] = str(e)
        print(f"  [SPY]  FAILED: {e}")
        return []


def fetch_bis(errors):
    """Only the 5R aggregates — the ratio's numerator and denominator.

    Deliberately NOT fetch_bis_credit(), which walks all 19 country codes and
    costs 19 SDMX round-trips. The ratio only ever uses "All reporting
    countries", so one call per sector is enough.
    """
    out = {}
    try:
        from data.gli_fetcher import _fetch_bis_single
    except Exception as e:                                  # noqa: BLE001
        errors["bis"] = f"cannot import BIS fetcher: {e}"
        print(f"  [BIS]  FAILED to import: {e}")
        return out

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    for name, sector in [("all_sector", "C"), ("private_nf", "P")]:
        try:
            s = _fetch_bis_single("5R", headers, borrowing_sector=sector).dropna()
            out[name] = _series_to_records(s)
            print(f"  [BIS]  {name:<11} {len(s):>4} obs  "
                  f"{s.index[0].date()} -> {s.index[-1].date()}")
        except Exception as e:                              # noqa: BLE001
            errors[f"bis_{name}"] = str(e)
            print(f"  [BIS]  {name:<11} FAILED: {e}")
    return out


def fetch_dollar_stress(errors):
    try:
        from data.dollar_stress import (
            fetch_dollar_stress_gist, parse_basis_swaps, build_dollar_stress_index,
        )
        idx = build_dollar_stress_index(parse_basis_swaps(fetch_dollar_stress_gist()))
        s = idx.dropna()
        print(f"  [XCCY] {len(s):>6} obs  {s.index[0].date()} -> {s.index[-1].date()}")
        return _series_to_records(s)
    except Exception as e:                                  # noqa: BLE001
        errors["dollar_stress"] = str(e)
        print(f"  [XCCY] FAILED: {e}")
        return []


def main():
    errors = {}
    print("Exporting full-history snapshot...")
    print("-" * 60)
    payload = {
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "observation_start": START,
        "fred": fetch_fred(errors),
        "fred_first_release": fetch_fred_first_release(errors),
        "spy": fetch_spy(errors),
        "bis": fetch_bis(errors),
        "dollar_stress": fetch_dollar_stress(errors),
        "errors": errors,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload))
    size_mb = OUT.stat().st_size / 1e6
    print("-" * 60)
    print(f"Wrote {OUT.relative_to(ROOT)}  ({size_mb:.1f} MB)")
    if errors:
        print(f"{len(errors)} source(s) failed — recorded in the file's 'errors' block:")
        for k, v in errors.items():
            print(f"   {k}: {str(v)[:100]}")
    if size_mb > 24:
        print("WARNING: over GitHub's 25 MB web-upload limit — push with git, not the browser.")
    print()
    print("Next:  git add research/snapshot && git commit -m 'Full-history snapshot' && git push")


if __name__ == "__main__":
    main()
