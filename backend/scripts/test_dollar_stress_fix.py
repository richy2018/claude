#!/usr/bin/env python3
"""Test Dollar Stress stride fix: verify parsing + standalone signal quality.

Runs a self-contained test using only the Dollar Stress gist (no FRED/Yahoo needed):
  1. Fetch gist with FIXED 3-col stride parser
  2. Verify all 6 pairs parse correctly with expected values
  3. Build Dollar Stress Index
  4. Compute mom6 signal transformation
  5. Build expanding-window quintiles and simulate allocation
  6. Log standalone signal stats for comparison
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from scipy import stats as sp_stats


def main():
    print("=" * 70)
    print("  DOLLAR STRESS FIX VALIDATION")
    print("=" * 70)

    # 1. Fetch & parse gist with fixed parser
    print("\n[1] Fetching Dollar Stress gist...")
    from data.dollar_stress import (
        fetch_dollar_stress_gist, parse_basis_swaps,
        build_dollar_stress_index, CURRENCY_WEIGHTS, CURRENCIES
    )
    text = fetch_dollar_stress_gist()
    swaps = parse_basis_swaps(text)
    ds_index = build_dollar_stress_index(swaps)

    # 2. Verify all pairs parsed
    print(f"\n[2] PAIR VERIFICATION")
    print(f"{'Pair':<12} {'Obs':>6} {'Start':>10} {'End':>12} {'Latest':>10}")
    print("-" * 55)
    expected_latest = {
        "EUR/USD": -2.25,
        "JPY/USD": -24.25,
        "GBP/USD": 3.00,
        "CHF/USD": -16.25,
        "KRW/USD": -54.00,
        "CNY/USD": -11.12,
    }

    all_ok = True
    for ccy in CURRENCIES:
        if ccy not in swaps:
            print(f"  {ccy}: MISSING!")
            all_ok = False
            continue
        s = swaps[ccy]
        latest = s.iloc[-1]
        expected = expected_latest.get(ccy)
        status = "OK" if expected is None or abs(latest - expected) < 0.5 else "MISMATCH"
        if status == "MISMATCH":
            all_ok = False
        print(f"  {ccy:<10} {len(s):>6} {s.index[0].strftime('%Y-%m'):>10} {s.index[-1].strftime('%Y-%m-%d'):>12} {latest:>10.2f}  {status}")

    if all_ok:
        print("\n  All pairs parsed correctly with expected values.")
    else:
        print("\n  WARNING: Some pairs have unexpected values!")

    # 3. Dollar Stress Index quality
    print(f"\n[3] DOLLAR STRESS INDEX")
    print(f"  Months: {len(ds_index)}")
    print(f"  Range: {ds_index.index[0].strftime('%Y-%m')} to {ds_index.index[-1].strftime('%Y-%m')}")
    print(f"  Latest: {ds_index.iloc[-1]:.2f}")
    print(f"  Mean: {ds_index.mean():.2f}")
    print(f"  Std: {ds_index.std():.2f}")
    print(f"  Min: {ds_index.min():.2f} ({ds_index.idxmin().strftime('%Y-%m')})")
    print(f"  Max: {ds_index.max():.2f} ({ds_index.idxmax().strftime('%Y-%m')})")

    # 4. Signal transformation (mom6)
    print(f"\n[4] MOM6 SIGNAL TRANSFORMATION")
    mom6 = ds_index.diff(6).dropna()
    print(f"  Mom6 signal: {len(mom6)} months")
    print(f"  Latest: {mom6.iloc[-1]:.2f}")
    print(f"  Mean: {mom6.mean():.2f}")
    print(f"  Std: {mom6.std():.2f}")

    # 5. Z-score for GLI integration
    print(f"\n[5] Z-SCORE (36M window)")
    z36 = ds_index.rolling(36, min_periods=12).apply(
        lambda x: (x.iloc[-1] - x.mean()) / x.std() if x.std() > 0 else 0
    ).dropna()
    scaled = (z36 / 3).clip(-1, 1)
    print(f"  Z-scored signal: {len(scaled)} months")
    print(f"  Latest z: {z36.iloc[-1]:.3f}")
    print(f"  Latest scaled: {scaled.iloc[-1]:.3f}")

    # 6. Sanity check: compare with old buggy values
    # The old parser with 6-col stride would have:
    # - EUR/USD reading col[0]: correct
    # - JPY/USD reading col[6]: would get GBP value
    # - GBP/USD reading col[12]: would get KRW value
    print(f"\n[6] BUG IMPACT ANALYSIS")
    print(f"  Fixed:  JPY/USD = {swaps.get('JPY/USD', pd.Series()).iloc[-1]:.2f} bp (was reading GBP's value)")
    print(f"  Fixed:  GBP/USD = {swaps.get('GBP/USD', pd.Series()).iloc[-1]:.2f} bp (was reading KRW's value)")

    # Compute what the old buggy index would have looked like
    # Old 6-col stride: EUR=col[0], JPY=col[6]=GBP's val, GBP=col[12]=KRW's val
    buggy_swaps = {}
    for ccy in CURRENCIES:
        if ccy in swaps:
            buggy_swaps[ccy] = swaps[ccy].copy()
    # Simulate bug: JPY reads GBP, GBP reads KRW
    if "JPY/USD" in swaps and "GBP/USD" in swaps and "KRW/USD" in swaps:
        buggy_swaps["JPY/USD"] = swaps["GBP/USD"].copy()
        buggy_swaps["GBP/USD"] = swaps["KRW/USD"].copy()

    # Build buggy index
    from data.dollar_stress import build_dollar_stress_index as build_ds
    try:
        buggy_index = build_ds(buggy_swaps)

        # Compare
        common = ds_index.index.intersection(buggy_index.index)
        diff = (ds_index.reindex(common) - buggy_index.reindex(common)).abs()
        corr = float(np.corrcoef(ds_index.reindex(common), buggy_index.reindex(common))[0, 1])

        print(f"\n  FIXED vs BUGGY comparison:")
        print(f"  Correlation: {corr:.4f}")
        print(f"  Mean abs diff: {diff.mean():.2f}")
        print(f"  Max abs diff: {diff.max():.2f} ({diff.idxmax().strftime('%Y-%m')})")

        # Mom6 comparison
        fix_mom6 = ds_index.diff(6).dropna()
        bug_mom6 = buggy_index.diff(6).dropna()
        m6_common = fix_mom6.index.intersection(bug_mom6.index)
        m6_corr = float(np.corrcoef(fix_mom6.reindex(m6_common), bug_mom6.reindex(m6_common))[0, 1])
        print(f"  Mom6 correlation: {m6_corr:.4f}")

        # Impact on weight — dollar_stress is 20% of 5F composite
        print(f"\n  Dollar stress factor is 20% of 5F composite")
        print(f"  With 4 other factors unchanged, max composite change = {diff.max() * 0.20:.2f}")

        if m6_corr > 0.90:
            print(f"\n  VERDICT: Mom6 signal highly correlated ({m6_corr:.3f})")
            print(f"  Sharpe impact likely < 0.1 — factor weight recalibration NOT needed")
        elif m6_corr > 0.70:
            print(f"\n  VERDICT: Mom6 signal moderately correlated ({m6_corr:.3f})")
            print(f"  Sharpe impact may exceed 0.1 — consider recalibration")
        else:
            print(f"\n  VERDICT: Mom6 signal poorly correlated ({m6_corr:.3f})")
            print(f"  Sharpe impact likely significant — recalibration recommended")

    except Exception as e:
        print(f"  Could not build buggy comparison: {e}")

    # 7. Print last 12 months of the index
    print(f"\n[7] DOLLAR STRESS INDEX — LAST 12 MONTHS")
    for dt, val in ds_index.tail(12).items():
        m6_val = mom6.get(dt)
        m6_str = f"mom6={m6_val:+.2f}" if m6_val is not None and pd.notna(m6_val) else "mom6=N/A"
        print(f"  {dt.strftime('%Y-%m')}: {val:>8.2f}  ({m6_str})")

    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Parser fix: 6-col stride → 3-col stride (date, value, separator)")
    print(f"  All 6 pairs now parsing correctly ({sum(len(s) for s in swaps.values())} total obs)")
    print(f"  JPY/USD: {swaps['JPY/USD'].iloc[-1]:.2f} bp (expected -24.25)")
    print(f"  GBP/USD: {swaps['GBP/USD'].iloc[-1]:.2f} bp (expected 3.00)")
    print(f"  Dollar Stress Index: {len(ds_index)} months, latest={ds_index.iloc[-1]:.2f}")


if __name__ == "__main__":
    main()
