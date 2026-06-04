#!/usr/bin/env python3
"""Probe BIS API for fresher dataflows.

Tests alternative series keys, valuation types, and dataflows to find
the most current total credit data for the Qty factor.

Run on Render (needs external network):
  python backend/scripts/probe_bis_freshness.py
"""

import requests
import pandas as pd
from io import StringIO
from datetime import date

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
}

TODAY = pd.Timestamp(date.today())


def _try_csv(url, label):
    """Fetch a BIS CSV URL and return (latest_date, n_obs) or None."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code != 200:
            print(f"  {label}: HTTP {resp.status_code}")
            return None
        if len(resp.text) < 200:
            print(f"  {label}: too short ({len(resp.text)} chars)")
            return None

        df = pd.read_csv(StringIO(resp.text))
        time_col = val_col = None
        for c in df.columns:
            cl = c.lower()
            if time_col is None and ("time_period" in cl or "period" in cl or "time" in cl):
                time_col = c
            if val_col is None and ("obs_value" in cl or cl == "value"):
                val_col = c

        if not time_col or not val_col:
            print(f"  {label}: no time/value columns in {list(df.columns)[:5]}")
            return None

        df["date"] = pd.to_datetime(df[time_col], errors="coerce")
        df["value"] = pd.to_numeric(df[val_col], errors="coerce")
        valid = df.dropna(subset=["date", "value"])

        if len(valid) == 0:
            print(f"  {label}: 0 valid obs")
            return None

        latest = valid["date"].max()
        behind = (TODAY - latest).days
        latest_val = float(valid.loc[valid["date"] == latest, "value"].iloc[0])
        print(f"  {label}: {len(valid)} obs, latest={latest.strftime('%Y-%m')} "
              f"({behind}d behind), val={latest_val:.1f}")
        return latest, len(valid), behind

    except Exception as e:
        print(f"  {label}: ERROR {e}")
        return None


def main():
    print("=" * 70)
    print("  BIS FRESHNESS PROBE")
    print(f"  Today: {TODAY.strftime('%Y-%m-%d')}")
    print("=" * 70)

    base_v2 = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0"

    # Current production query
    print("\n--- CURRENT PRODUCTION (WS_TC/2.0, 5R, sector C, M=market, USD, A=adjusted) ---")
    _try_csv(f"{base_v2}/Q.5R.C.A.M.USD.A?format=csv", "PROD C (all-sector)")
    _try_csv(f"{base_v2}/Q.5R.P.A.M.USD.A?format=csv", "PROD P (private-NF)")

    # Test: Nominal (N) instead of Market (M) — often published sooner
    print("\n--- VALUATION: N=Nominal vs M=Market ---")
    _try_csv(f"{base_v2}/Q.5R.C.A.N.USD.A?format=csv", "Nominal C (all-sector)")
    _try_csv(f"{base_v2}/Q.5R.P.A.N.USD.A?format=csv", "Nominal P (private-NF)")

    # Test: domestic currency (XDC) instead of USD
    print("\n--- CURRENCY: XDC=Domestic vs USD ---")
    _try_csv(f"{base_v2}/Q.US.C.A.M.XDC.A?format=csv", "US domestic ccy C")
    _try_csv(f"{base_v2}/Q.US.P.A.M.XDC.A?format=csv", "US domestic ccy P")

    # Test: US specifically (might publish ahead of 5R aggregate)
    print("\n--- US ONLY (faster than 5R aggregate?) ---")
    _try_csv(f"{base_v2}/Q.US.C.A.M.USD.A?format=csv", "US USD M C")
    _try_csv(f"{base_v2}/Q.US.P.A.M.USD.A?format=csv", "US USD M P")

    # Test: Not break-adjusted (N instead of A for last dim)
    print("\n--- ADJUSTMENT: N=Not-adjusted vs A=Adjusted ---")
    _try_csv(f"{base_v2}/Q.5R.C.A.M.USD.N?format=csv", "Not-adjusted C")
    _try_csv(f"{base_v2}/Q.5R.P.A.M.USD.N?format=csv", "Not-adjusted P")

    # Test: WS_TC version 1.0 (older dataflow, might have different schedule)
    print("\n--- DATAFLOW: WS_TC/1.0 (older version) ---")
    base_v1 = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/1.0"
    _try_csv(f"{base_v1}/Q.5R.C.A.M.USD.A?format=csv", "v1.0 C")
    _try_csv(f"{base_v1}/Q.5R.P.A.M.USD.A?format=csv", "v1.0 P")

    # Test: BIS credit-to-GDP gap (WS_CREDIT_GAP) — different dataflow entirely
    print("\n--- DATAFLOW: WS_CREDIT_GAP (credit-to-GDP gap) ---")
    gap_base = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CREDIT_GAP/1.0"
    _try_csv(f"{gap_base}/Q.US.C?format=csv", "US credit gap C")
    _try_csv(f"{gap_base}/Q.5R.C?format=csv", "5R credit gap C")

    # Test: BIS LBS (Locational Banking Statistics) — monthly, much fresher
    print("\n--- DATAFLOW: WS_LBS (Locational Banking Stats, monthly) ---")
    lbs_base = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LBS_D_PUB/1.0"
    _try_csv(f"{lbs_base}/Q.S.5R.A.TO1.A.5J.A.USD.A.A?format=csv", "LBS total claims")

    # Test: BIS CBS (Consolidated Banking Statistics)
    print("\n--- DATAFLOW: WS_CBS (Consolidated Banking Stats) ---")
    cbs_base = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBS_PUB/1.0"
    _try_csv(f"{cbs_base}/Q.S.5R.N.B.USD.A?format=csv", "CBS total claims")

    print("\n" + "=" * 70)
    print("  SUMMARY: Compare 'days behind' across variants above.")
    print("  If Nominal(N) or Not-adjusted(N) is fresher than Market(M)/Adjusted(A),")
    print("  switching the production query gains months of freshness.")
    print("=" * 70)


if __name__ == "__main__":
    main()


def probe_global_liquidity():
    """Probe BIS Global Liquidity indicators (WS_GLI) — different from WS_TC."""
    print("\n" + "=" * 70)
    print("  BIS GLOBAL LIQUIDITY DATAFLOWS")
    print("=" * 70)

    # WS_GLI — Global Liquidity Indicators
    # Reference: https://www.bis.org/statistics/gli.htm
    gli_bases = [
        ("WS_GLI/1.0", "GLI v1.0"),
        ("WS_GLI/2.0", "GLI v2.0"),
        ("WS_GLI_CRED/1.0", "GLI Credit v1.0"),
        ("WS_GLI_CRED/2.0", "GLI Credit v2.0"),
    ]

    # Common GLI keys:
    # Q.{measure}.{borrower}.{currency}.{country}
    # Measures: I=international, D=domestic, T=total
    # Borrower: N=non-bank, B=bank, A=all
    # Currency: USD, XDC, TO1(all currencies)
    gli_keys = [
        "Q.T.N.USD.5R",    # Total credit to non-bank, USD, all reporting
        "Q.T.A.USD.5R",    # Total credit to all, USD, all reporting
        "Q.I.N.USD.5R",    # International credit to non-bank
        "Q.D.N.USD.5R",    # Domestic credit to non-bank
        "Q.T.N.TO1.5R",    # Total credit, all currencies
        "Q.T.N.USD.US",    # Total credit to non-bank, USD, US
    ]

    for base_label, base_name in gli_bases:
        base_url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/{base_label}"
        print(f"\n--- {base_name} ---")
        for key in gli_keys:
            url = f"{base_url}/{key}?format=csv"
            _try_csv(url, f"{base_name} {key}")

    # Also try the GLI-specific total credit dataflow keys on WS_TC
    print("\n--- WS_TC/2.0 with broader key patterns ---")
    tc_base = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0"
    extra_keys = [
        "Q.5R.C.A.M.USD.N",    # Not break-adjusted (diff last dim)
        "Q.5R.C.D.M.USD.A",    # D=domestic lenders only
        "Q.5R.C.B.M.USD.A",    # B=banks only
        "Q.5R.N.A.M.USD.A",    # N=non-financial (different borrower code?)
    ]
    for key in extra_keys:
        url = f"{tc_base}/{key}?format=csv"
        _try_csv(url, f"WS_TC {key}")


if __name__ != "__main__":
    pass
else:
    probe_global_liquidity()
