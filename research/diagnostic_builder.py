#!/usr/bin/env python3
"""GLI Signal Filter Research — Phase 1: Diagnostic Dataset Construction.

Builds a labeled dataset of every Q4/Q5 signal occurrence with:
  - Forward performance metrics (returns, drawdowns)
  - TP/FP labels (multiple definitions)
  - Macro context variables at signal time

Usage:
  FRED_API_KEY=your_key python research/diagnostic_builder.py
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime

# Add project root and backend to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "backend"))

from research.config import (
    SIGNAL_START, SIGNAL_END, OUTPUT_DIR, DIAGNOSTICS_CSV, SUMMARY_TXT,
    TP_STRICT_DD, TP_MODERATE_DD, TP_LOOSE_RETURN,
    TP_COMBINED_DD, TP_COMBINED_RETURN,
)
from research.data_loaders import (
    fetch_fred_data, fetch_yf_data, build_gli_signal,
    fetch_fred_data_via_api, fetch_yf_data_via_api, build_gli_signal_via_api,
    RENDER_URL,
)
from research.macro_features import (
    fetch_shiller_data, build_monthly_cache, compute_all_features,
)


def compute_forward_metrics(signal_date, spy_monthly_close, spy_daily_close):
    """Compute forward performance metrics from signal_date.

    Returns dict with fwd returns and max drawdowns.
    No look-ahead: these are forward-looking BY DESIGN (for labeling).
    """
    result = {}

    # Monthly forward returns (cumulative)
    monthly_after = spy_monthly_close.loc[signal_date:]
    if len(monthly_after) < 2:
        return result

    base_price = float(monthly_after.iloc[0])

    for months, key in [(1, "fwd_1m_return"), (3, "fwd_3m_return"),
                        (6, "fwd_6m_return"), (12, "fwd_12m_return")]:
        if len(monthly_after) > months:
            fwd_price = float(monthly_after.iloc[months])
            result[key] = (fwd_price / base_price - 1) * 100
        else:
            result[key] = np.nan

    # Forward max drawdowns using daily data for precision
    daily_after = spy_daily_close.loc[signal_date:]
    if len(daily_after) < 5:
        return result

    daily_base = float(daily_after.iloc[0])

    for months, key in [(6, "fwd_6m_max_drawdown"), (12, "fwd_12m_max_drawdown")]:
        # Approximate: months * 21 trading days
        n_days = min(months * 21, len(daily_after) - 1)
        if n_days < 5:
            result[key] = np.nan
            continue
        window = daily_after.iloc[:n_days + 1]
        peak = window.expanding().max()
        drawdowns = (window - peak) / peak
        result[key] = float(drawdowns.min()) * 100  # percentage

    return result


def label_tp_fp(row):
    """Apply TP/FP labels based on forward metrics."""
    labels = {}

    # Strict: fwd 6m max drawdown <= -10%
    dd6 = row.get("fwd_6m_max_drawdown")
    labels["label_strict_tp"] = int(dd6 <= TP_STRICT_DD * 100) if pd.notna(dd6) else np.nan

    # Moderate: fwd 6m max drawdown <= -7%
    labels["label_moderate_tp"] = int(dd6 <= TP_MODERATE_DD * 100) if pd.notna(dd6) else np.nan

    # Loose: fwd 3m return < 0
    ret3 = row.get("fwd_3m_return")
    labels["label_loose_tp"] = int(ret3 < TP_LOOSE_RETURN * 100) if pd.notna(ret3) else np.nan

    # Combined: fwd 6m max drawdown <= -7% OR fwd 3m return < -5%
    if pd.notna(dd6) and pd.notna(ret3):
        labels["label_combined_tp"] = int(
            dd6 <= TP_COMBINED_DD * 100 or ret3 < TP_COMBINED_RETURN * 100
        )
    else:
        labels["label_combined_tp"] = np.nan

    return labels


def compute_quintile_duration(quintiles):
    """Compute consecutive months at each quintile level.

    Returns pd.Series with same index as quintiles.
    """
    durations = pd.Series(0, index=quintiles.index, dtype=int)
    streak = 1
    for i in range(len(quintiles)):
        if i == 0:
            durations.iloc[i] = 1
        elif quintiles.iloc[i] == quintiles.iloc[i-1]:
            streak += 1
            durations.iloc[i] = streak
        else:
            streak = 1
            durations.iloc[i] = streak
    return durations


def build_diagnostics():
    """Main orchestration: build the Q4/Q5 diagnostic dataset."""
    print("=" * 70)
    print("  GLI SIGNAL FILTER RESEARCH — Phase 1")
    print("  Diagnostic Dataset Construction")
    print("=" * 70)

    # ── 1. Fetch all data ────────────────────────────────────────────────
    # Auto-detect mode: use API if RENDER_URL is set, otherwise direct fetch
    use_api = bool(RENDER_URL)
    mode = "API" if use_api else "DIRECT"
    print(f"\n[1/5] Fetching data sources (mode: {mode})...")

    if use_api:
        print(f"  Using backend API: {RENDER_URL}")
        print("\n  --- FRED (via API) ---")
        fred_data = fetch_fred_data_via_api()
        print("\n  --- yfinance (via API) ---")
        yf_data = fetch_yf_data_via_api()
        print("\n  --- Shiller ---")
        shiller_data = fetch_shiller_data()  # try direct; may fail
        if not shiller_data:
            print("  Shiller data unavailable — CAPE/EPS columns will be NaN")
            shiller_data = {}
    else:
        print("\n  --- FRED ---")
        fred_data = fetch_fred_data()
        print("\n  --- yfinance ---")
        yf_data = fetch_yf_data()
        print("\n  --- Shiller ---")
        shiller_data = fetch_shiller_data()

    # ── 2. Build GLI signal ──────────────────────────────────────────────
    print("\n[2/5] Building GLI 5F production signal...")
    if use_api:
        gli = build_gli_signal_via_api()
    else:
        gli = build_gli_signal(fred_data)
    quintiles = gli["quintiles"]
    signal = gli["signal"]

    # ── 3. Prepare market data ───────────────────────────────────────────
    print("\n[3/5] Preparing market data...")

    spy_daily = yf_data.get("SPY")
    if spy_daily is None:
        raise RuntimeError("SPY data not available — set RENDER_URL or ensure yfinance network access")

    spy_monthly = spy_daily.resample("MS").last().ffill()

    # Build monthly and daily caches for feature computation
    monthly_cache = build_monthly_cache(fred_data, yf_data, shiller_data)
    daily_cache = {"SPY": spy_daily}

    # ── 4. Filter to Q4/Q5 signals in date range ────────────────────────
    print("\n[4/5] Building diagnostic rows...")

    start = pd.Timestamp(SIGNAL_START)
    end = pd.Timestamp(SIGNAL_END)
    mask = (quintiles.index >= start) & (quintiles.index <= end) & (quintiles >= 4)
    q45_signals = quintiles[mask]

    print(f"  Total Q4/Q5 signals in range: {len(q45_signals)}")
    print(f"  Q4: {(q45_signals == 4).sum()}, Q5: {(q45_signals == 5).sum()}")

    # Compute quintile durations
    durations = compute_quintile_duration(quintiles)

    # ── Build each row ───────────────────────────────────────────────────
    rows = []
    for i, (date, q) in enumerate(q45_signals.items()):
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  Processing signal {i+1}/{len(q45_signals)}: "
                  f"{date.strftime('%Y-%m')} Q{q}")

        row = {
            "signal_date": date.strftime("%Y-%m-%d"),
            "quintile": int(q),
            "quintile_duration": int(durations.loc[date]) if date in durations.index else 1,
        }

        # Forward performance
        fwd = compute_forward_metrics(date, spy_monthly, spy_daily)
        row.update(fwd)

        # TP/FP labels
        labels = label_tp_fp(row)
        row.update(labels)

        # Macro context
        features = compute_all_features(date, monthly_cache, daily_cache, fred_data)
        row.update(features)

        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"\n  Diagnostic dataset: {len(df)} rows, {len(df.columns)} columns")

    # ── 5. Save outputs ──────────────────────────────────────────────────
    print("\n[5/5] Saving outputs...")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(DIAGNOSTICS_CSV, index=False)
    print(f"  Saved: {DIAGNOSTICS_CSV}")

    # ── Summary statistics ───────────────────────────────────────────────
    summary_lines = []
    summary_lines.append("=" * 60)
    summary_lines.append("GLI Signal Filter Research — Phase 1 Summary")
    summary_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    summary_lines.append("=" * 60)

    summary_lines.append(f"\nDate range: {SIGNAL_START} to {SIGNAL_END}")
    summary_lines.append(f"Total Q4 signals: {(df['quintile'] == 4).sum()}")
    summary_lines.append(f"Total Q5 signals: {(df['quintile'] == 5).sum()}")
    summary_lines.append(f"Total Q4+Q5 signals: {len(df)}")

    if "signal_date" in df.columns:
        summary_lines.append(f"First signal: {df['signal_date'].iloc[0]}")
        summary_lines.append(f"Last signal: {df['signal_date'].iloc[-1]}")

    summary_lines.append("\n--- TP Rate by Label Definition ---")
    for label_col in ["label_strict_tp", "label_moderate_tp", "label_loose_tp", "label_combined_tp"]:
        if label_col in df.columns:
            valid = df[label_col].dropna()
            if len(valid) > 0:
                tp_rate = valid.mean() * 100
                summary_lines.append(f"  {label_col}: {tp_rate:.1f}% ({int(valid.sum())}/{len(valid)})")

    # Q5-only TP rates
    q5_only = df[df["quintile"] == 5]
    if len(q5_only) > 0:
        summary_lines.append("\n--- TP Rate (Q5 only) ---")
        for label_col in ["label_strict_tp", "label_moderate_tp", "label_loose_tp", "label_combined_tp"]:
            if label_col in q5_only.columns:
                valid = q5_only[label_col].dropna()
                if len(valid) > 0:
                    tp_rate = valid.mean() * 100
                    summary_lines.append(f"  {label_col}: {tp_rate:.1f}% ({int(valid.sum())}/{len(valid)})")

    # Macro variable means
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    macro_cols = [c for c in numeric_cols if c not in
                  ["quintile", "quintile_duration", "fwd_1m_return", "fwd_3m_return",
                   "fwd_6m_return", "fwd_12m_return", "fwd_6m_max_drawdown",
                   "fwd_12m_max_drawdown", "label_strict_tp", "label_moderate_tp",
                   "label_loose_tp", "label_combined_tp"]]

    if macro_cols:
        summary_lines.append("\n--- Macro Variable Summary (mean / median) ---")
        for col in sorted(macro_cols):
            valid = df[col].dropna()
            if len(valid) > 0:
                summary_lines.append(f"  {col}: mean={valid.mean():.2f}, median={valid.median():.2f}")

    # Missing data
    summary_lines.append("\n--- Missing Values ---")
    for col in df.columns:
        missing = df[col].isna().sum()
        pct = missing / len(df) * 100
        if pct > 0:
            flag = " *** FLAG: >10% missing" if pct > 10 else ""
            summary_lines.append(f"  {col}: {missing} ({pct:.1f}%){flag}")

    summary_text = "\n".join(summary_lines)
    with open(SUMMARY_TXT, "w") as f:
        f.write(summary_text)
    print(f"  Saved: {SUMMARY_TXT}")

    # ── Terminal output ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  RESULTS")
    print("=" * 70)

    # TP rate comparison
    print("\n  TP RATE COMPARISON (Q4+Q5)")
    print(f"  {'Label':<25} {'TP Rate':>10} {'TP':>5} {'Total':>7}")
    print("  " + "-" * 50)
    for label_col in ["label_strict_tp", "label_moderate_tp", "label_loose_tp", "label_combined_tp"]:
        if label_col in df.columns:
            valid = df[label_col].dropna()
            if len(valid) > 0:
                print(f"  {label_col:<25} {valid.mean()*100:>9.1f}% {int(valid.sum()):>5} {len(valid):>7}")

    # Top 5 TRUE POSITIVE Q5 signals (worst forward drawdowns)
    q5_df = df[df["quintile"] == 5].copy()
    if len(q5_df) > 0 and "fwd_6m_max_drawdown" in q5_df.columns:
        print("\n  TOP 5 Q5 TRUE POSITIVES (worst fwd 6M drawdown)")
        print(f"  {'Date':<12} {'DD 6M':>8} {'Ret 3M':>8} {'Ret 6M':>8} {'Ret 12M':>9}")
        print("  " + "-" * 50)
        worst = q5_df.nsmallest(5, "fwd_6m_max_drawdown")
        for _, r in worst.iterrows():
            print(f"  {r['signal_date']:<12} "
                  f"{r.get('fwd_6m_max_drawdown', np.nan):>7.1f}% "
                  f"{r.get('fwd_3m_return', np.nan):>7.1f}% "
                  f"{r.get('fwd_6m_return', np.nan):>7.1f}% "
                  f"{r.get('fwd_12m_return', np.nan):>8.1f}%")

    # Top 5 FALSE POSITIVE Q5 signals (best forward returns despite Q5)
    if len(q5_df) > 0 and "label_strict_tp" in q5_df.columns and "fwd_6m_return" in q5_df.columns:
        fp_df = q5_df[q5_df["label_strict_tp"] == 0].copy()
        if len(fp_df) > 0:
            print("\n  TOP 5 Q5 FALSE POSITIVES (highest fwd 6M return, strict label)")
            print(f"  {'Date':<12} {'DD 6M':>8} {'Ret 3M':>8} {'Ret 6M':>8} {'Ret 12M':>9}")
            print("  " + "-" * 50)
            best_fp = fp_df.nlargest(5, "fwd_6m_return")
            for _, r in best_fp.iterrows():
                print(f"  {r['signal_date']:<12} "
                      f"{r.get('fwd_6m_max_drawdown', np.nan):>7.1f}% "
                      f"{r.get('fwd_3m_return', np.nan):>7.1f}% "
                      f"{r.get('fwd_6m_return', np.nan):>7.1f}% "
                      f"{r.get('fwd_12m_return', np.nan):>8.1f}%")

    # Quintile distribution in full signal
    print(f"\n  FULL SIGNAL QUINTILE DISTRIBUTION ({SIGNAL_START} to {SIGNAL_END})")
    full_range = quintiles[(quintiles.index >= pd.Timestamp(SIGNAL_START)) &
                           (quintiles.index <= pd.Timestamp(SIGNAL_END))]
    for q in range(1, 6):
        n = (full_range == q).sum()
        pct = n / len(full_range) * 100
        print(f"  Q{q}: {n:>4} ({pct:>5.1f}%)")

    print(f"\n  Total observations: {len(full_range)}")
    print(f"\n  Dataset saved to: {DIAGNOSTICS_CSV}")
    print(f"  Summary saved to: {SUMMARY_TXT}")


if __name__ == "__main__":
    build_diagnostics()
