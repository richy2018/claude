#!/usr/bin/env python3
"""GLI Signal Filter Research — Phase 1: Diagnostic Dataset Construction.

Builds a labeled dataset of every Q4/Q5 signal occurrence with:
  - Forward performance metrics (returns, drawdowns)
  - TP/FP labels (multiple definitions)
  - Macro context variables at signal time

Usage (standalone):
  FRED_API_KEY=your_key python research/diagnostic_builder.py

Usage (as module):
  from research.diagnostic_builder import run_diagnostic
  result = run_diagnostic(fred_api_key="...")
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


def _safe_float(v):
    """Convert to float, returning None for NaN."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return round(float(v), 4)
    except (ValueError, TypeError):
        return None


def _safe_str(v):
    """Convert to string, returning None for NaN."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return str(v)


def _tp_rate(series):
    """Compute TP rate from a label series, returning float or None."""
    valid = series.dropna()
    if len(valid) == 0:
        return None
    return round(float(valid.mean()) * 100, 1)


def _build_top_row(r):
    """Build a structured dict for a top TP/FP row."""
    return {
        "signal_date": r.get("signal_date"),
        "quintile": f"Q{int(r['quintile'])}" if pd.notna(r.get("quintile")) else None,
        "fwd_6m_max_drawdown": _safe_float(r.get("fwd_6m_max_drawdown")),
        "fwd_3m_return": _safe_float(r.get("fwd_3m_return")),
        "fwd_6m_return": _safe_float(r.get("fwd_6m_return")),
        "fwd_12m_return": _safe_float(r.get("fwd_12m_return")),
        "hy_oas": _safe_float(r.get("hy_oas")),
        "fed_regime": _safe_str(r.get("fed_regime")),
        "curve_regime": _safe_str(r.get("curve_regime")),
        "dxy_regime": _safe_str(r.get("dxy_regime")),
        "growth_regime": _safe_str(r.get("growth_regime")),
        "earnings_regime": _safe_str(r.get("earnings_regime")),
        "vix_level": _safe_float(r.get("vix_level")),
    }


def run_diagnostic(fred_api_key=None, use_cache=True):
    """Run Phase 1 diagnostic and return structured results.

    Args:
        fred_api_key: defaults to env var FRED_API_KEY
        use_cache: if True, return cached result if generated within last 24h

    Returns:
        dict with summary, top_true_positives, top_false_positives,
        full_dataset, quintile_distribution.
    """
    if fred_api_key:
        os.environ["FRED_API_KEY"] = fred_api_key

    warnings = []

    # ── 1. Fetch data ────────────────────────────────────────────────────
    use_api = bool(RENDER_URL)
    print(f"[DIAG] Fetching data (mode: {'API' if use_api else 'DIRECT'})...")

    try:
        if use_api:
            fred_data = fetch_fred_data_via_api()
        else:
            fred_data = fetch_fred_data()
    except Exception as e:
        warnings.append(f"FRED fetch failed: {e}")
        fred_data = {}

    try:
        if use_api:
            yf_data = fetch_yf_data_via_api()
        else:
            yf_data = fetch_yf_data()
    except Exception as e:
        warnings.append(f"yfinance fetch failed: {e}")
        yf_data = {}

    try:
        shiller_data = fetch_shiller_data()
    except Exception:
        shiller_data = {}
        warnings.append("Shiller data unavailable — CAPE/EPS columns will be NaN")

    # ── 2. Build GLI signal ──────────────────────────────────────────────
    print("[DIAG] Building GLI 5F production signal...")
    try:
        if use_api:
            gli = build_gli_signal_via_api()
        else:
            gli = build_gli_signal(fred_data)
    except Exception as e:
        return {"error": f"GLI signal build failed: {e}", "warnings": warnings}

    quintiles = gli["quintiles"]
    signal = gli["signal"]

    # ── 3. Prepare market data ───────────────────────────────────────────
    spy_daily = yf_data.get("SPY")
    if spy_daily is None:
        return {"error": "SPY data not available", "warnings": warnings}

    spy_monthly = spy_daily.resample("MS").last().ffill()
    monthly_cache = build_monthly_cache(fred_data, yf_data, shiller_data)
    daily_cache = {"SPY": spy_daily}

    # ── 4. Build diagnostic rows ─────────────────────────────────────────
    print("[DIAG] Building diagnostic rows...")

    start = pd.Timestamp(SIGNAL_START)
    end = pd.Timestamp(SIGNAL_END)
    mask = (quintiles.index >= start) & (quintiles.index <= end) & (quintiles >= 4)
    q45_signals = quintiles[mask]
    durations = compute_quintile_duration(quintiles)

    rows = []
    for i, (date, q) in enumerate(q45_signals.items()):
        if (i + 1) % 20 == 0:
            print(f"[DIAG] Processing {i+1}/{len(q45_signals)}...")

        row = {
            "signal_date": date.strftime("%Y-%m-%d"),
            "quintile": int(q),
            "quintile_duration": int(durations.loc[date]) if date in durations.index else 1,
        }

        fwd = compute_forward_metrics(date, spy_monthly, spy_daily)
        row.update(fwd)

        labels = label_tp_fp(row)
        row.update(labels)

        features = compute_all_features(date, monthly_cache, daily_cache, fred_data)
        row.update(features)

        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"[DIAG] Dataset: {len(df)} rows, {len(df.columns)} columns")

    # ── 5. Build structured result ───────────────────────────────────────

    # TP rates
    tp_rates = {}
    for label_key, label_col in [("strict", "label_strict_tp"),
                                  ("moderate", "label_moderate_tp"),
                                  ("loose", "label_loose_tp"),
                                  ("combined", "label_combined_tp")]:
        if label_col in df.columns:
            tp_rates[label_key] = _tp_rate(df[label_col])

    # Missing data flags
    missing_flags = []
    for col in df.columns:
        pct = df[col].isna().sum() / len(df) * 100 if len(df) > 0 else 0
        if pct > 10:
            missing_flags.append(f"{col}: {pct:.0f}% missing")

    # Top true positives (worst forward drawdowns, Q4+Q5)
    top_tp = []
    if "fwd_6m_max_drawdown" in df.columns:
        worst = df.nsmallest(5, "fwd_6m_max_drawdown")
        for _, r in worst.iterrows():
            top_tp.append(_build_top_row(r))

    # Top false positives: Q5 signals where fwd_6m_return > +5%
    top_fp = []
    q5_df = df[df["quintile"] == 5].copy()
    if len(q5_df) > 0 and "fwd_6m_return" in q5_df.columns:
        fp_candidates = q5_df[q5_df["fwd_6m_return"] > 5.0]
        best_fp = fp_candidates.nlargest(5, "fwd_6m_return") if len(fp_candidates) > 0 else q5_df.nlargest(5, "fwd_6m_return")
        for _, r in best_fp.iterrows():
            top_fp.append(_build_top_row(r))

    # Quintile distribution (full signal)
    full_range = quintiles[(quintiles.index >= start) & (quintiles.index <= end)]
    q_dist = {}
    for q in range(1, 6):
        q_dist[f"Q{q}"] = int((full_range == q).sum())

    # Full dataset as records
    full_dataset = []
    for _, r in df.iterrows():
        record = {}
        for col in df.columns:
            val = r[col]
            if isinstance(val, (np.integer, np.int64)):
                record[col] = int(val)
            elif isinstance(val, (np.floating, np.float64)):
                record[col] = None if np.isnan(val) else round(float(val), 4)
            else:
                record[col] = val
        full_dataset.append(record)

    result = {
        "summary": {
            "total_q4_q5_signals": len(df),
            "q4_count": int((df["quintile"] == 4).sum()),
            "q5_count": int((df["quintile"] == 5).sum()),
            "tp_rates": tp_rates,
            "fp_definition": "Q5 signal where fwd 6m return > +5%",
            "date_range": [
                df["signal_date"].iloc[0] if len(df) > 0 else None,
                df["signal_date"].iloc[-1] if len(df) > 0 else None,
            ],
            "missing_data_flags": missing_flags,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "from_cache": False,
            "warnings": warnings,
        },
        "top_true_positives": top_tp,
        "top_false_positives": top_fp,
        "full_dataset": full_dataset,
        "quintile_distribution": q_dist,
    }

    # Also save CSV/summary for standalone use
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        df.to_csv(DIAGNOSTICS_CSV, index=False)
    except Exception:
        pass

    return result


def build_diagnostics():
    """Main orchestration for standalone CLI use."""
    print("=" * 70)
    print("  GLI SIGNAL FILTER RESEARCH — Phase 1")
    print("  Diagnostic Dataset Construction")
    print("=" * 70)

    result = run_diagnostic(use_cache=False)

    if "error" in result:
        print(f"\n  ERROR: {result['error']}")
        if result.get("warnings"):
            for w in result["warnings"]:
                print(f"  WARNING: {w}")
        return

    s = result["summary"]
    print("\n" + "=" * 70)
    print("  RESULTS")
    print("=" * 70)

    print(f"\n  Total Q4/Q5 signals: {s['total_q4_q5_signals']} (Q4: {s['q4_count']}, Q5: {s['q5_count']})")
    print(f"  Date range: {s['date_range'][0]} to {s['date_range'][1]}")

    print("\n  TP RATE COMPARISON (Q4+Q5)")
    print(f"  {'Label':<25} {'TP Rate':>10}")
    print("  " + "-" * 40)
    for k, v in s["tp_rates"].items():
        print(f"  {k:<25} {v:>9.1f}%" if v is not None else f"  {k:<25}       N/A")

    print("\n  TOP 5 TRUE POSITIVES (worst fwd 6M drawdown)")
    print(f"  {'Date':<12} {'Qtle':>5} {'DD 6M':>8} {'Ret 3M':>8} {'Ret 6M':>8}")
    print("  " + "-" * 45)
    for r in result["top_true_positives"]:
        dd = r["fwd_6m_max_drawdown"]
        r3 = r["fwd_3m_return"]
        r6 = r["fwd_6m_return"]
        print(f"  {r['signal_date']:<12} {r['quintile']:>5} "
              f"{dd:>7.1f}% " if dd else "    N/A ",
              f"{r3:>7.1f}% " if r3 else "    N/A ",
              f"{r6:>7.1f}%" if r6 else "    N/A")

    print(f"\n  TOP 5 FALSE POSITIVES (Q5, fwd 6M ret > +5%)")
    for r in result["top_false_positives"]:
        print(f"  {r['signal_date']}  {r['quintile']}  fwd_6m={r['fwd_6m_return']}%")

    print(f"\n  QUINTILE DISTRIBUTION")
    for q, n in result["quintile_distribution"].items():
        print(f"  {q}: {n}")

    if s["missing_data_flags"]:
        print(f"\n  MISSING DATA FLAGS:")
        for f in s["missing_data_flags"]:
            print(f"    {f}")

    print(f"\n  Dataset saved to: {DIAGNOSTICS_CSV}")


if __name__ == "__main__":
    build_diagnostics()
