#!/usr/bin/env python3
"""Refresh the FINRA margin-debt cached store (backend/data/margin_debt.csv).

FINRA Margin Statistics — "Debit Balances in Customers' Securities Margin
Accounts" (monthly, USD millions). FINRA provides NO API/feed: only a
downloadable xlsx beginning January 1997.

  https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics

Monthly refresh cadence
-----------------------
FINRA publishes month M's figure in the THIRD WEEK of month M+1. Run this
script after each release to refresh the store, then commit the updated CSV.

Usage
-----
  python backend/scripts/update_margin_debt.py            # download + parse FINRA xlsx
  python backend/scripts/update_margin_debt.py --url URL  # override source xlsx URL
  python backend/scripts/update_margin_debt.py --seed     # write placeholder seed store

The script is robust to FINRA column/format drift: it searches for the
debit-balance column by header keywords and FAILS LOUDLY with a clear message
if the schema can no longer be matched, rather than writing garbage.
"""

import argparse
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "margin_debt.csv"

# FINRA margin statistics xlsx (the public download; may change — override via --url)
DEFAULT_FINRA_URL = "https://www.finra.org/sites/default/files/2024-03/margin-statistics.xlsx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# Header keywords used to locate the debit-balance column (case-insensitive)
DEBIT_KEYWORDS = ["debit balances in customers", "debit balances", "debit"]
DATE_KEYWORDS = ["month/year", "month", "period", "date", "year-month"]


def _find_col(columns, keyword_lists):
    """Return the first column whose lowercased name contains any keyword."""
    lowered = {c: str(c).strip().lower() for c in columns}
    for keywords in keyword_lists:
        kw = keywords if isinstance(keywords, list) else [keywords]
        for c, lc in lowered.items():
            if any(k in lc for k in kw):
                return c
    return None


def fetch_and_parse_finra(url):
    """Download the FINRA xlsx and parse the debit-balance monthly series.

    Returns pd.Series indexed by reference-month Timestamp (USD millions).
    Raises RuntimeError with a clear message if the schema can't be matched.
    """
    import requests
    print(f"[FINRA] Downloading {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"FINRA download failed: HTTP {resp.status_code} from {url}")
    if len(resp.content) < 1000:
        raise RuntimeError(f"FINRA download too small ({len(resp.content)} bytes) — wrong URL?")

    # Try each sheet; FINRA sometimes nests the table under a title row
    xls = pd.ExcelFile(BytesIO(resp.content))
    print(f"[FINRA] Workbook sheets: {xls.sheet_names}")

    last_err = None
    for sheet in xls.sheet_names:
        for header_row in range(0, 6):
            try:
                df = pd.read_excel(xls, sheet_name=sheet, header=header_row)
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
            date_col = _find_col(df.columns, [DATE_KEYWORDS])
            debit_col = _find_col(df.columns, [DEBIT_KEYWORDS])
            if date_col is not None and debit_col is not None:
                print(f"[FINRA] Matched sheet='{sheet}' header_row={header_row} "
                      f"date_col='{date_col}' debit_col='{debit_col}'")
                return _build_series(df, date_col, debit_col)

    raise RuntimeError(
        "FINRA SCHEMA DRIFT: could not locate date + debit-balance columns in any "
        f"sheet/header. Sheets={xls.sheet_names}. Last error={last_err}. "
        "Inspect the xlsx and update DEBIT_KEYWORDS/DATE_KEYWORDS in this script."
    )


def _build_series(df, date_col, debit_col):
    """Build a clean monthly series from the matched columns."""
    dates = pd.to_datetime(df[date_col], errors="coerce")
    values = pd.to_numeric(
        df[debit_col].astype(str).str.replace(",", "").str.replace("$", "", regex=False),
        errors="coerce")
    s = pd.Series(values.values, index=dates).dropna()
    s = s[~s.index.isna()]
    # Normalize to month-start reference dates
    s.index = s.index.to_period("M").to_timestamp("M").to_period("M").to_timestamp()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if len(s) < 24:
        raise RuntimeError(f"FINRA parse produced only {len(s)} rows — likely wrong column.")
    print(f"[FINRA] Parsed {len(s)} months, {s.index[0]:%Y-%m} → {s.index[-1]:%Y-%m}, "
          f"latest={s.iloc[-1]:,.0f} USD M")
    return s


def write_csv(series, source_note):
    """Write the tidy series to the CSV store with a source provenance line."""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="") as f:
        f.write(f"# source: {source_note}\n")
        f.write("# FINRA Margin Statistics — Debit Balances in Customers' Securities "
                "Margin Accounts (USD millions)\n")
        f.write("# Publication lag: month M released ~3rd week of M+1\n")
        f.write("date,margin_debt_usd_m\n")
        for d, v in series.items():
            f.write(f"{d.strftime('%Y-%m-%d')},{v:.1f}\n")
    print(f"[FINRA] Wrote {len(series)} rows → {CSV_PATH}")


def build_seed_series():
    """Deterministic PLACEHOLDER series (2015-01 .. 2026-03).

    Anchored to a handful of well-known FINRA margin-debt levels with linear
    interpolation between anchors. NOT authoritative — clearly labelled as a
    seed so the dashboard flags it until real FINRA data is fetched. Run
    without --seed on a networked host to replace with authoritative values.
    """
    anchors = {
        "2015-01": 465000, "2015-12": 449000,
        "2016-12": 504000, "2017-12": 642000,
        "2018-01": 665700, "2018-05": 668900, "2018-12": 554300,
        "2019-12": 579800, "2020-03": 479300, "2020-12": 778000,
        "2021-10": 935900, "2021-12": 910000,
        "2022-09": 657000, "2022-12": 632000,
        "2023-06": 663000, "2023-12": 700000,
        "2024-06": 809000, "2024-12": 815000,
        "2025-06": 920000, "2025-12": 1010000, "2026-03": 1050000,
    }
    idx = pd.period_range("2015-01", "2026-03", freq="M").to_timestamp()
    anchor_s = pd.Series({pd.Timestamp(k + "-01"): float(v) for k, v in anchors.items()})
    anchor_s = anchor_s.reindex(idx).interpolate(method="time").ffill().bfill()
    anchor_s.name = "margin_debt_usd_m"
    return anchor_s.round(0)


def main():
    ap = argparse.ArgumentParser(description="Refresh FINRA margin-debt store")
    ap.add_argument("--url", default=DEFAULT_FINRA_URL, help="Override FINRA xlsx URL")
    ap.add_argument("--seed", action="store_true", help="Write placeholder seed store")
    args = ap.parse_args()

    if args.seed:
        s = build_seed_series()
        write_csv(s, "SEED PLACEHOLDER (run update_margin_debt.py for authoritative FINRA data)")
        print("[FINRA] Seed store written. This is NOT authoritative data.")
        return

    try:
        s = fetch_and_parse_finra(args.url)
    except Exception as e:  # noqa: BLE001
        print(f"\n[FINRA] FAILED: {e}\n", file=sys.stderr)
        sys.exit(1)

    write_csv(s, f"FINRA xlsx {args.url} fetched {date.today().isoformat()}")
    print("[FINRA] Done. Commit margin_debt.csv to deploy the update.")


if __name__ == "__main__":
    main()
