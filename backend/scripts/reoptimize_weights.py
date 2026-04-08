#!/usr/bin/env python3
"""Re-optimize production model weights after Dollar Stress parser fix.

Run this script after a REFRESH on the deployed backend to recompute
optimal weights for 4F, 3FB, and 2F models using the corrected
5-pair Dollar Stress Index.

Usage:
    # From the backend directory:
    python -m scripts.reoptimize_weights

    # Or set FRED_API_KEY if not already in env:
    FRED_API_KEY=your_key python -m scripts.reoptimize_weights

Requires: pandas, numpy, scipy, yfinance, requests
"""

import sys
import os
import json
import numpy as np
import pandas as pd

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def fetch_spy_monthly():
    """Fetch SPY monthly close prices."""
    import yfinance as yf
    spy = yf.download("SPY", start="2003-01-01", progress=False)
    if spy.empty:
        raise RuntimeError("Failed to fetch SPY data")
    spy_close = spy["Close"]
    if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
        spy_close = spy_close.droplevel(1)
    if isinstance(spy_close, pd.DataFrame):
        spy_close = spy_close.iloc[:, 0]
    return spy_close.resample("MS").last().dropna()


def fetch_fred_series(series_ids):
    """Fetch multiple FRED series. Returns DataFrame."""
    from fredapi import Fred
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        raise RuntimeError("FRED_API_KEY not set. Export it first.")
    fred = Fred(api_key=api_key)
    frames = {}
    for sid in series_ids:
        try:
            s = fred.get_series(sid, observation_start="2000-01-01")
            frames[sid] = pd.to_numeric(s, errors="coerce")
            print(f"  [FRED] {sid}: {len(s)} obs")
        except Exception as e:
            print(f"  [FRED] {sid}: FAILED ({e})")
    return pd.DataFrame(frames)


def build_ratio_series_from_fred(fred_df, dollar_stress_index):
    """Build a minimal ratio_series from FRED data + dollar stress.

    This replicates the compute_debt_liquidity_ratio signal computation
    without requiring BIS credit data. We synthesize the quantity signal
    from M2 growth as a proxy for the debt/liquidity ratio RoC.
    """
    from models.gli_engine import compute_debt_liquidity_ratio

    # We don't have BIS data, so use M2 as proxy for both credit aggregates
    # The ratio won't be meaningful, but the SIGNALS are what matter
    m2 = fred_df.get("M2SL")
    if m2 is None:
        raise RuntimeError("M2SL not in FRED data")

    m2_m = m2.resample("MS").last().ffill().dropna()
    # Synthetic "total credit" and "private NF credit" from M2
    # The ratio is just a vehicle to get the component signals computed
    total_credit = m2_m * 1.6  # approximate scaling
    private_nf = m2_m

    policy_rate = None
    hy_spread = None
    yield_curve = None
    m2_supply = None

    for col in ["DFF", "FEDFUNDS"]:
        if col in fred_df.columns:
            policy_rate = fred_df[col].dropna()
            break
    if "BAMLH0A0HYM2" in fred_df.columns:
        hy_spread = fred_df["BAMLH0A0HYM2"].dropna()
    if "T10Y2Y" in fred_df.columns:
        yield_curve = fred_df["T10Y2Y"].dropna()
    if "M2SL" in fred_df.columns:
        m2_supply = fred_df["M2SL"].dropna()

    result = compute_debt_liquidity_ratio(
        total_credit, private_nf,
        policy_rate=policy_rate,
        hy_spread=hy_spread,
        yield_curve=yield_curve,
        m2_supply=m2_supply,
        dollar_stress=dollar_stress_index,
    )

    return result.get("ratio_series", [])


def run_model_sweep(ratio_series, spy_m, model_name):
    """Run sweep for a single model and return top config with weights."""
    from models.backtest_engine import run_sweep

    print(f"\n{'='*60}")
    print(f"  SWEEP: {model_name.upper()}")
    print(f"{'='*60}")

    result = run_sweep(ratio_series, spy_m, model=model_name)

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return None

    lb = result.get("leaderboard", [])
    if not lb:
        print("  No configs passed filters.")
        return None

    print(f"\n  Top 10 configs (by OOS 6M correlation):")
    print(f"  {'Rank':<5} {'Signal':<12} {'Filter':<12} {'OOS Corr':<10} {'Spread':<8} {'Mono':<8} {'N':<6} {'FW Mean':<10}")
    print(f"  {'-'*71}")
    for i, entry in enumerate(lb[:10]):
        fw = entry.get("fw_fixed_mean", "--")
        fw_str = f"{fw:.4f}" if isinstance(fw, float) else str(fw)
        print(f"  {i+1:<5} {entry['signal']:<12} {entry['filter']:<12} "
              f"{entry.get('oos_corr_6m', '--'):<10} "
              f"{entry.get('spread_6m', '--'):<8} "
              f"{entry.get('monotonicity', '--'):<8} "
              f"{entry.get('n', '--'):<6} "
              f"{fw_str:<10}")

    # Extract best config with walk-forward weights
    best = None
    for entry in lb[:10]:
        if entry.get("fw_fixed_weights"):
            best = entry
            break

    if best:
        print(f"\n  BEST CONFIG: signal={best['signal']}, filter={best['filter']}")
        print(f"  OOS Corr: {best.get('oos_corr_6m')}")
        print(f"  FW Fixed Mean: {best.get('fw_fixed_mean')}")
        print(f"  Optimized weights:")
        for k, v in best["fw_fixed_weights"].items():
            print(f"    {k}: {v:.4f}")
        return best
    else:
        print("  No config had walk-forward weights.")
        return None


def main():
    print("=" * 60)
    print("  PRODUCTION MODEL WEIGHT RE-OPTIMIZATION")
    print("  (after Dollar Stress parser fix — all 5 pairs)")
    print("=" * 60)

    # 1. Fetch corrected Dollar Stress Index
    print("\n[1] Fetching corrected Dollar Stress Index...")
    from data.dollar_stress import fetch_dollar_stress_gist, parse_basis_swaps, build_dollar_stress_index
    gist_text = fetch_dollar_stress_gist()
    raw_swaps = parse_basis_swaps(gist_text)
    ds_index = build_dollar_stress_index(raw_swaps)
    print(f"  Dollar Stress: {len(ds_index)} months, "
          f"{ds_index.index[0].strftime('%Y-%m')} to {ds_index.index[-1].strftime('%Y-%m')}")

    # 2. Fetch FRED data
    print("\n[2] Fetching FRED data...")
    fred_series = ["DFF", "FEDFUNDS", "BAMLH0A0HYM2", "T10Y2Y", "M2SL"]
    fred_df = fetch_fred_series(fred_series)

    # 3. Build ratio_series
    print("\n[3] Building ratio_series...")
    ratio_series = build_ratio_series_from_fred(fred_df, ds_index)
    print(f"  ratio_series: {len(ratio_series)} months")

    if len(ratio_series) < 60:
        print("  ERROR: Not enough data for optimization. Need at least 60 months.")
        sys.exit(1)

    # 4. Fetch SPY
    print("\n[4] Fetching SPY monthly data...")
    spy_m = fetch_spy_monthly()
    print(f"  SPY: {len(spy_m)} months")

    # 5. Run sweeps for all 3 models
    models_to_sweep = ["4f", "3fb", "2f"]
    results = {}

    for model in models_to_sweep:
        best = run_model_sweep(ratio_series, spy_m, model)
        if best:
            results[model] = best

    # 6. Output summary
    print("\n" + "=" * 60)
    print("  SUMMARY — NEW PRODUCTION WEIGHTS")
    print("=" * 60)

    for model in models_to_sweep:
        if model in results:
            best = results[model]
            w = best["fw_fixed_weights"]
            print(f"\n  {model.upper()}:")
            print(f"    Signal: {best['signal']}, Filter: {best['filter']}")
            print(f"    OOS Corr: {best.get('oos_corr_6m')}, FW Mean: {best.get('fw_fixed_mean')}")
            print(f"    Weights:")
            for k, v in w.items():
                print(f"      \"{k}\": {v:.2f},")
        else:
            print(f"\n  {model.upper()}: No valid result")

    # 7. Generate code snippet for PRODUCTION_MODELS update
    print("\n" + "=" * 60)
    print("  COPY-PASTE INTO backtest_engine.py PRODUCTION_MODELS:")
    print("=" * 60)

    from models.backtest_engine import MODEL_CONFIGS
    for model in models_to_sweep:
        if model not in results:
            continue
        best = results[model]
        w = best["fw_fixed_weights"]
        cfg = MODEL_CONFIGS[model]
        keys_str = str(cfg["keys"])
        w_str = json.dumps(w, indent=None)
        sig = best["signal"]
        print(f'''
    "{model}": {{
        "keys": {keys_str},
        "weights": {w_str},
        "label": "{cfg['label']}",
        "signal_type": "{sig}",
        "description": "{cfg.get('description', '')}",
    }},''')


if __name__ == "__main__":
    main()
