"""Phase 3 — Filtered Signal Backtest.

Compares equity curves for the production GLI signal (unfiltered)
against each Phase 2 filter rule (A, B, C) and SPY buy-and-hold.

Structured in three layers:
  3A.1: Core metrics (equity_curves, metrics, deltas, subperiod_sharpes, alpha_decomp)
  3A.2: Crash detection + drawdowns + rule_a_filter_triggers
  3A.3: Monte Carlo + recommendation with criterion-level reasoning

Usage (as module from backend):
  from research.phase3_backtest import run_phase3_backtest
  result = run_phase3_backtest(phase2_result, gli_data, spy_daily)
"""

import numpy as np
import pandas as pd
from datetime import datetime

from research.config import ALLOC_MAP

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUBPERIODS = [
    ("Pre-GFC", "2003-01-01", "2007-06-30"),
    ("GFC", "2007-07-01", "2009-06-30"),
    ("Recovery", "2009-07-01", "2015-12-31"),
    ("Late Cycle", "2016-01-01", "2019-12-31"),
    ("COVID+", "2020-01-01", None),
]

VARIANT_LABELS = {
    "no_filter": "No Filter (Production)",
    "rule_a": "Rule A: Credit-Only",
    "rule_b": "Rule B: Credit + Growth",
    "rule_c": "Rule C: Credit + Growth + Curve",
    "buyhold": "SPY Buy & Hold",
}


# ---------------------------------------------------------------------------
# Metric helpers (match backtest_engine.py conventions)
# ---------------------------------------------------------------------------

def _ann_ret(eq):
    """Annualized return from equity curve (indexed at 1.0 start)."""
    years = len(eq) / 12
    if eq.iloc[-1] <= 0 or years < 0.5:
        return 0.0
    return float(eq.iloc[-1] ** (1 / years) - 1)


def _ann_vol(rets):
    """Annualized volatility from monthly returns."""
    return float(rets.std() * np.sqrt(12))


def _max_dd(eq):
    """Maximum drawdown from equity curve."""
    peak = eq.expanding().max()
    dd = (eq - peak) / peak
    return float(dd.min())


def _sharpe(rets):
    """Sharpe ratio from monthly returns (rf=0)."""
    ar = _ann_ret((1 + rets).cumprod())
    av = _ann_vol(rets)
    return round(ar / av, 3) if av > 0 else 0.0


def _sortino(rets, mar=0.0):
    """Sortino ratio from monthly returns."""
    if len(rets) < 12:
        return 0.0
    excess = rets - mar / 12
    downside = excess.clip(upper=0)
    downside_dev = float(np.sqrt((downside ** 2).mean()) * np.sqrt(12))
    ar = _ann_ret((1 + rets).cumprod())
    return round(ar / downside_dev, 3) if downside_dev > 0 else 0.0


def _calmar(rets):
    """Calmar ratio from monthly returns."""
    eq = (1 + rets).cumprod()
    ar = _ann_ret(eq)
    dd = abs(_max_dd(eq))
    return round(ar / dd, 2) if dd > 0.001 else 0.0


# ---------------------------------------------------------------------------
# 3A.1 — Core simulation
# ---------------------------------------------------------------------------

def _build_filtered_quintiles(original_quintiles, filtered_signals_list):
    """Apply Phase 2 filter overrides to original quintile series.

    For each date where a filter triggered, override Q4/Q5 → Q3.

    Args:
        original_quintiles: pd.Series with Q1-Q5 for all months
        filtered_signals_list: list of dicts from Phase 2's filtered_signals,
            each with signal_date, original_quintile, filtered_quintile,
            filter_triggered

    Returns:
        pd.Series with overridden quintiles.
    """
    result = original_quintiles.copy()

    override_dates = set()
    for row in filtered_signals_list:
        if row.get("filter_triggered"):
            override_dates.add(row["signal_date"])

    for dt in result.index:
        dt_str = dt.strftime("%Y-%m-%d")
        if dt_str in override_dates:
            result[dt] = 3

    return result


def _simulate_variant(quintiles, spy_returns, alloc_map):
    """Simulate equity curve for one variant.

    Args:
        quintiles: pd.Series of Q1-Q5 (DatetimeIndex, month-start)
        spy_returns: pd.Series of monthly SPY returns (DatetimeIndex)
        alloc_map: dict {quintile_int: weight_float}

    Returns:
        dict with equity (pd.Series), returns (pd.Series), weights, quintiles
        or None if insufficient data.
    """
    aligned = pd.DataFrame({
        "quintile": quintiles,
        "spy_ret": spy_returns,
    }).dropna()

    if len(aligned) < 12:
        return None

    weights = aligned["quintile"].map(alloc_map).astype(float)
    port_ret = aligned["spy_ret"] * weights
    port_eq = (1 + port_ret).cumprod()

    return {
        "equity": port_eq,
        "returns": port_ret,
        "weights": weights,
        "quintiles": aligned["quintile"],
    }


def _compute_metrics(sim):
    """Compute performance metrics from a simulation result."""
    if sim is None:
        return None

    eq = sim["equity"]
    rets = sim["returns"]

    return {
        "total_return": round(float(eq.iloc[-1] - 1) * 100, 1),
        "annualized_return": round(_ann_ret(eq) * 100, 2),
        "annualized_vol": round(_ann_vol(rets) * 100, 2),
        "sharpe": _sharpe(rets),
        "sortino": _sortino(rets),
        "max_drawdown": round(_max_dd(eq) * 100, 1),
        "calmar": _calmar(rets),
    }


def _delta(a, b, metric_name):
    """Compute delta between two metric values with direction indicator.

    For max_drawdown, less negative (closer to 0) is better, so a positive
    delta means improvement.  For all other metrics, higher is better.
    """
    diff = round(a - b, 2)
    if abs(diff) < 0.005:
        direction = "flat"
    elif diff > 0:
        direction = "better"
    else:
        direction = "worse"
    return {"value": diff, "direction": direction}


def _compute_deltas(metrics_dict):
    """Compute deltas between all rule variants vs no_filter and vs buyhold."""
    deltas = {}
    delta_metrics = [
        "annualized_return", "sharpe", "sortino", "max_drawdown", "calmar",
    ]

    nf_m = metrics_dict.get("no_filter")
    bh_m = metrics_dict.get("buyhold")

    # Rule variants vs no_filter and vs buyhold
    for key in metrics_dict:
        if not key.startswith("rule_"):
            continue
        rule_m = metrics_dict[key]
        if not rule_m:
            continue

        if nf_m:
            deltas[f"{key}_vs_no_filter"] = {
                m: _delta(rule_m[m], nf_m[m], m) for m in delta_metrics
            }
        if bh_m:
            deltas[f"{key}_vs_buyhold"] = {
                m: _delta(rule_m[m], bh_m[m], m) for m in delta_metrics
            }

    # no_filter vs buyhold
    if nf_m and bh_m:
        deltas["no_filter_vs_buyhold"] = {
            m: _delta(nf_m[m], bh_m[m], m) for m in delta_metrics
        }

    return deltas


def _compute_subperiod_sharpes(returns_dict, subperiods):
    """Compute Sharpe ratio for each variant in each subperiod.

    Returns:
        {period_name: {variant: sharpe_or_None, ...}, ...}
    """
    result = {}

    for name, start, end in subperiods:
        period_sharpes = {}
        for variant, rets in returns_dict.items():
            mask = rets.index >= pd.Timestamp(start)
            if end is not None:
                mask &= rets.index <= pd.Timestamp(end)
            period_rets = rets[mask]

            if len(period_rets) >= 12:
                period_sharpes[variant] = _sharpe(period_rets)
            else:
                period_sharpes[variant] = None

        result[name] = period_sharpes

    return result


def _compute_alpha_decomp(portfolio_returns, market_returns):
    """CAPM alpha decomposition via OLS regression.

    Regresses portfolio excess returns on market excess returns (rf=0).

    Returns:
        dict with alpha_annual_pct, beta, r_squared, t_stat, significant
    """
    aligned = pd.concat([
        portfolio_returns.rename("port"),
        market_returns.rename("mkt"),
    ], axis=1).dropna()

    null_result = {
        "alpha_annual_pct": 0.0,
        "beta": 1.0,
        "r_squared": 0.0,
        "t_stat": 0.0,
        "significant": False,
    }

    if len(aligned) < 24:
        return null_result

    y = aligned["port"].values
    x = aligned["mkt"].values
    X = np.column_stack([np.ones(len(x)), x])

    try:
        beta_hat = np.linalg.lstsq(X, y, rcond=None)[0]
        alpha_monthly = beta_hat[0]
        beta = beta_hat[1]

        y_pred = X @ beta_hat
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        n = len(y)
        mse = ss_res / max(n - 2, 1)
        XtX_inv = np.linalg.inv(X.T @ X)
        se_alpha = np.sqrt(mse * XtX_inv[0, 0])
        t_stat = alpha_monthly / se_alpha if se_alpha > 0 else 0.0

        alpha_annual = (1 + alpha_monthly) ** 12 - 1

        return {
            "alpha_annual_pct": round(alpha_annual * 100, 2),
            "beta": round(float(beta), 3),
            "r_squared": round(float(r_sq), 3),
            "t_stat": round(float(t_stat), 2),
            "significant": abs(t_stat) > 1.96,
        }
    except Exception:
        return null_result


# ---------------------------------------------------------------------------
# 3A.2 — Crash detection + drawdowns + filter triggers
# ---------------------------------------------------------------------------

CRASH_THRESHOLD = -0.15  # 15% peak-to-trough triggers crash detection


def _detect_crash_episodes(spy_equity):
    """Detect crash episodes from SPY equity curve.

    A crash episode starts when drawdown breaches CRASH_THRESHOLD and ends
    when equity recovers to the prior peak.

    Returns:
        list of dicts with start, trough, end, depth_pct, duration_months
    """
    peak = spy_equity.expanding().max()
    dd = (spy_equity - peak) / peak

    episodes = []
    in_crash = False
    start = None
    trough_date = None
    trough_val = 0.0

    for dt, dd_val in dd.items():
        if not in_crash and dd_val <= CRASH_THRESHOLD:
            in_crash = True
            # Walk back to find when drawdown first went negative
            start = dt
            for prev_dt in reversed(dd.loc[:dt].index):
                if dd[prev_dt] >= 0:
                    start = prev_dt
                    break
            trough_date = dt
            trough_val = dd_val
        elif in_crash:
            if dd_val < trough_val:
                trough_date = dt
                trough_val = dd_val
            if dd_val >= 0:
                # Recovery complete
                episodes.append({
                    "start": start.strftime("%Y-%m-%d"),
                    "trough": trough_date.strftime("%Y-%m-%d"),
                    "end": dt.strftime("%Y-%m-%d"),
                    "depth_pct": round(float(trough_val) * 100, 1),
                    "duration_months": len(dd.loc[start:dt]),
                })
                in_crash = False

    # If still in crash at end of series
    if in_crash:
        episodes.append({
            "start": start.strftime("%Y-%m-%d"),
            "trough": trough_date.strftime("%Y-%m-%d"),
            "end": None,
            "depth_pct": round(float(trough_val) * 100, 1),
            "duration_months": len(dd.loc[start:]),
        })

    return episodes


def _compute_crash_detection(spy_equity, sims):
    """For each SPY crash episode, compute each variant's drawdown.

    Returns:
        list of crash episode dicts with variant_drawdowns
    """
    episodes = _detect_crash_episodes(spy_equity)

    for ep in episodes:
        start = pd.Timestamp(ep["start"])
        end_str = ep.get("end")
        end = pd.Timestamp(end_str) if end_str else spy_equity.index[-1]

        variant_drawdowns = {}
        for name, sim in sims.items():
            if sim is None:
                continue
            eq = sim["equity"]
            period_eq = eq.loc[start:end]
            if len(period_eq) > 0:
                period_peak = period_eq.expanding().max()
                period_dd = (period_eq - period_peak) / period_peak
                variant_drawdowns[name] = round(float(period_dd.min()) * 100, 1)
            else:
                variant_drawdowns[name] = 0.0

        ep["variant_drawdowns"] = variant_drawdowns

    return episodes


def _compute_drawdowns(sim, top_n=5):
    """Compute detailed drawdown analysis for a single variant.

    Returns:
        dict with current_drawdown and worst_drawdowns list
    """
    if sim is None:
        return None

    eq = sim["equity"]
    peak = eq.expanding().max()
    dd = (eq - peak) / peak

    current_dd = round(float(dd.iloc[-1]) * 100, 1)

    # Identify all drawdown episodes
    episodes = []
    in_dd = False
    start = None
    trough_date = None
    trough_val = 0.0

    for dt, dd_val in dd.items():
        if not in_dd and dd_val < -0.01:  # 1% threshold to start tracking
            in_dd = True
            start = dt
            trough_date = dt
            trough_val = dd_val
        elif in_dd:
            if dd_val < trough_val:
                trough_date = dt
                trough_val = dd_val
            if dd_val >= 0:
                duration = len(dd.loc[start:dt])
                recovery = len(dd.loc[trough_date:dt])
                episodes.append({
                    "start": start.strftime("%Y-%m-%d"),
                    "trough": trough_date.strftime("%Y-%m-%d"),
                    "end": dt.strftime("%Y-%m-%d"),
                    "depth_pct": round(float(trough_val) * 100, 1),
                    "duration_months": duration,
                    "recovery_months": recovery,
                })
                in_dd = False

    # Still in drawdown at end
    if in_dd and trough_val < -0.01:
        duration = len(dd.loc[start:])
        episodes.append({
            "start": start.strftime("%Y-%m-%d"),
            "trough": trough_date.strftime("%Y-%m-%d"),
            "end": None,
            "depth_pct": round(float(trough_val) * 100, 1),
            "duration_months": duration,
            "recovery_months": None,
        })

    # Sort by depth (worst first)
    episodes.sort(key=lambda e: e["depth_pct"])

    return {
        "current_drawdown": current_dd,
        "worst_drawdowns": episodes[:top_n],
    }


def _build_filter_triggers(filtered_signals_list, spy_returns):
    """Build detailed filter trigger analysis for a rule.

    For each date the filter triggered, compute forward SPY returns
    to assess whether the filter call was correct.

    Args:
        filtered_signals_list: list of dicts from Phase 2 filtered_signals
        spy_returns: pd.Series of monthly SPY returns

    Returns:
        list of trigger dicts with forward returns and correctness assessment
    """
    triggers = []

    for row in filtered_signals_list:
        if not row.get("filter_triggered"):
            continue

        date_str = row["signal_date"]
        dt = pd.Timestamp(date_str)

        # Forward returns from SPY
        fwd_3m = None
        fwd_6m = None

        idx = spy_returns.index
        dt_pos = idx.searchsorted(dt)

        if dt_pos < len(idx):
            # 3-month forward return
            end_3m = min(dt_pos + 3, len(idx))
            if end_3m > dt_pos:
                fwd_3m = round(float((1 + spy_returns.iloc[dt_pos:end_3m]).prod() - 1) * 100, 2)

            # 6-month forward return
            end_6m = min(dt_pos + 6, len(idx))
            if end_6m > dt_pos:
                fwd_6m = round(float((1 + spy_returns.iloc[dt_pos:end_6m]).prod() - 1) * 100, 2)

        # Was the filter correct? (reducing exposure during negative forward period)
        was_correct = None
        if fwd_3m is not None:
            was_correct = fwd_3m < 0

        triggers.append({
            "date": date_str,
            "original_quintile": row["original_quintile"],
            "filtered_quintile": row["filtered_quintile"],
            "fwd_3m_spy_return": fwd_3m,
            "fwd_6m_spy_return": fwd_6m,
            "was_correct": was_correct,
        })

    return triggers


# ---------------------------------------------------------------------------
# 3A.1 — Main orchestration: Core metrics
# ---------------------------------------------------------------------------

def run_phase3_backtest_core(phase2_result, gli_data, spy_daily):
    """Run core Phase 3 backtest (Subtask 3A.1).

    Args:
        phase2_result: dict from run_phase2_analysis() with 'filtered_signals',
                       'winning_rule', 'rule_comparisons'
        gli_data: dict from build_gli_signal() with 'quintiles' (pd.Series Q1-Q5)
        spy_daily: pd.Series of daily SPY close prices (DatetimeIndex)

    Returns:
        dict with keys:
          - equity_curves: {variant: [{"date", "value"}, ...]}
          - metrics: {variant: {total_return, annualized_return, ...}}
          - deltas: {comparison: {metric: {"value", "direction"}, ...}}
          - subperiod_sharpes: {period: {variant: sharpe, ...}}
          - alpha_decomp: {variant: {alpha_annual_pct, beta, ...}}
          - summary: {n_months, date_range, variants, ...}
    """
    print("[PHASE3] Starting core backtest...")

    # ── 1. Prepare data ─────────────────────────────────────────────────
    original_quintiles = gli_data["quintiles"]

    spy_monthly = spy_daily.resample("MS").last().ffill()
    spy_returns = spy_monthly.pct_change().dropna()

    # Align to common date range
    common_idx = original_quintiles.index.intersection(spy_returns.index)
    if len(common_idx) < 24:
        return {"error": f"Insufficient overlapping data: {len(common_idx)} months"}

    original_quintiles = original_quintiles.reindex(common_idx)
    spy_returns = spy_returns.reindex(common_idx)

    print(f"[PHASE3] {len(common_idx)} months, "
          f"{common_idx[0].strftime('%Y-%m')} to {common_idx[-1].strftime('%Y-%m')}")

    # ── 2. Build variant quintile series ─────────────────────────────────
    filtered_signals = phase2_result.get("filtered_signals", {})

    variant_quintiles = {"no_filter": original_quintiles}
    for rule_name in ["rule_a", "rule_b", "rule_c"]:
        fs = filtered_signals.get(rule_name, [])
        if fs:
            variant_quintiles[rule_name] = _build_filtered_quintiles(
                original_quintiles, fs
            )
        else:
            variant_quintiles[rule_name] = original_quintiles.copy()

    # Count filter triggers per rule
    for rule_name in ["rule_a", "rule_b", "rule_c"]:
        fs = filtered_signals.get(rule_name, [])
        n_triggers = sum(1 for r in fs if r.get("filter_triggered"))
        print(f"[PHASE3] {rule_name}: {n_triggers} filter triggers")

    # ── 3. Simulate each variant ─────────────────────────────────────────
    alloc_map = ALLOC_MAP

    sims = {}
    for name, quints in variant_quintiles.items():
        sims[name] = _simulate_variant(quints, spy_returns, alloc_map)
        if sims[name]:
            print(f"[PHASE3] {name}: {len(sims[name]['equity'])} months simulated")

    # Buy-and-hold baseline
    bh_returns = spy_returns.dropna()
    bh_equity = (1 + bh_returns).cumprod()
    bh_metrics = {
        "total_return": round(float(bh_equity.iloc[-1] - 1) * 100, 1),
        "annualized_return": round(_ann_ret(bh_equity) * 100, 2),
        "annualized_vol": round(_ann_vol(bh_returns) * 100, 2),
        "sharpe": _sharpe(bh_returns),
        "sortino": _sortino(bh_returns),
        "max_drawdown": round(_max_dd(bh_equity) * 100, 1),
        "calmar": _calmar(bh_returns),
    }

    # ── 4. Compute metrics ───────────────────────────────────────────────
    metrics = {}
    for name, sim in sims.items():
        metrics[name] = _compute_metrics(sim)
    metrics["buyhold"] = bh_metrics

    # ── 5. Equity curves for chart ───────────────────────────────────────
    equity_curves = {}
    for name, sim in sims.items():
        if sim:
            equity_curves[name] = [
                {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
                for d, v in sim["equity"].items()
            ]
    equity_curves["buyhold"] = [
        {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
        for d, v in bh_equity.items()
    ]

    # ── 6. Deltas ────────────────────────────────────────────────────────
    deltas = _compute_deltas(metrics)

    # ── 7. Subperiod Sharpe ratios ───────────────────────────────────────
    returns_dict = {}
    for name, sim in sims.items():
        if sim:
            returns_dict[name] = sim["returns"]
    returns_dict["buyhold"] = bh_returns

    subperiod_sharpes = _compute_subperiod_sharpes(returns_dict, SUBPERIODS)

    # ── 8. Alpha decomposition ───────────────────────────────────────────
    alpha_decomp = {}
    for name, sim in sims.items():
        if sim:
            alpha_decomp[name] = _compute_alpha_decomp(sim["returns"], bh_returns)

    # ── 9. Summary ───────────────────────────────────────────────────────
    winning_rule = phase2_result.get("winning_rule", "rule_a")

    valid_variants = [k for k in metrics if k != "buyhold" and metrics[k]]
    best_variant = max(valid_variants, key=lambda k: metrics[k]["sharpe"])

    summary = {
        "n_months": len(common_idx),
        "date_range": [
            common_idx[0].strftime("%Y-%m-%d"),
            common_idx[-1].strftime("%Y-%m-%d"),
        ],
        "variants": list(variant_quintiles.keys()),
        "phase2_winning_rule": winning_rule,
        "best_backtest_variant": best_variant,
        "alloc_map": {str(k): v for k, v in alloc_map.items()},
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "from_cache": False,
    }

    print(f"[PHASE3] Core backtest complete. Best variant: {best_variant} "
          f"(Sharpe={metrics[best_variant]['sharpe']})")

    return {
        "equity_curves": equity_curves,
        "metrics": metrics,
        "deltas": deltas,
        "subperiod_sharpes": subperiod_sharpes,
        "alpha_decomp": alpha_decomp,
        "summary": summary,
        # Internal state for 3A.2/3A.3 extensions (stripped by run_phase3_backtest)
        "_internals": {
            "sims": sims,
            "spy_returns": spy_returns,
            "bh_equity": bh_equity,
            "bh_returns": bh_returns,
            "filtered_signals": filtered_signals,
        },
    }


# ---------------------------------------------------------------------------
# 3A.2 — Extended backtest: crash detection + drawdowns + filter triggers
# ---------------------------------------------------------------------------

def run_phase3_backtest_with_drawdowns(phase2_result, gli_data, spy_daily):
    """Run Phase 3 backtest with crash detection and drawdowns (3A.1 + 3A.2).

    Extends the core result with:
      - crash_detection: list of crash episodes with per-variant drawdowns
      - drawdowns: {variant: {current_drawdown, worst_drawdowns}}
      - rule_a_filter_triggers: list of trigger events with forward returns

    Returns:
        dict with all 3A.1 keys plus crash_detection, drawdowns,
        rule_a_filter_triggers
    """
    result = run_phase3_backtest_core(phase2_result, gli_data, spy_daily)
    if "error" in result:
        return result

    internals = result.pop("_internals")
    sims = internals["sims"]
    spy_returns = internals["spy_returns"]
    bh_equity = internals["bh_equity"]
    bh_returns = internals["bh_returns"]
    filtered_signals = internals["filtered_signals"]

    # ── 10. Crash detection ──────────────────────────────────────────────
    print("[PHASE3] Detecting crash episodes...")
    crash_detection = _compute_crash_detection(bh_equity, sims)
    print(f"[PHASE3] {len(crash_detection)} crash episodes detected")
    result["crash_detection"] = crash_detection

    # ── 11. Drawdowns per variant ────────────────────────────────────────
    print("[PHASE3] Computing drawdown tables...")
    drawdowns = {}
    for name, sim in sims.items():
        drawdowns[name] = _compute_drawdowns(sim)
    # Also compute for buy-and-hold
    drawdowns["buyhold"] = _compute_drawdowns({
        "equity": bh_equity,
        "returns": bh_returns,
    })
    result["drawdowns"] = drawdowns

    # ── 12. Filter trigger analysis (all rules) ─────────────────────────
    print("[PHASE3] Building filter trigger analysis...")
    for rule_name in ["rule_a", "rule_b", "rule_c"]:
        fs = filtered_signals.get(rule_name, [])
        triggers = _build_filter_triggers(fs, spy_returns)
        n_correct = sum(1 for t in triggers if t["was_correct"])
        n_total = sum(1 for t in triggers if t["was_correct"] is not None)
        accuracy = round(n_correct / n_total * 100, 1) if n_total > 0 else 0
        result[f"{rule_name}_filter_triggers"] = triggers
        print(f"[PHASE3] {rule_name}: {len(triggers)} triggers, "
              f"{n_correct}/{n_total} correct ({accuracy}%)")

    print("[PHASE3] 3A.2 complete.")

    # Store internals for 3A.3 extension
    result["_internals"] = internals
    return result


# ---------------------------------------------------------------------------
# 3A.3 — Monte Carlo + recommendation
# ---------------------------------------------------------------------------

MC_N_PERMUTATIONS = 10000


def _monte_carlo_sharpe_test(quintiles, spy_returns, alloc_map, n_perms=MC_N_PERMUTATIONS):
    """Permutation test for signal timing value.

    Fixes the SPY return sequence and shuffles quintile assignments to build
    a null distribution of Sharpes achievable by random timing.

    Args:
        quintiles: pd.Series of Q1-Q5 assignments
        spy_returns: pd.Series of monthly SPY returns (aligned)
        alloc_map: dict {quintile: weight}
        n_perms: number of permutations

    Returns:
        dict with actual_sharpe, permuted distribution stats, p_value
    """
    aligned = pd.DataFrame({
        "q": quintiles, "ret": spy_returns,
    }).dropna()

    if len(aligned) < 24:
        return {
            "actual_sharpe": 0.0, "p_value": 1.0, "significant": False,
            "permuted_mean": 0.0, "permuted_std": 0.0,
            "percentile_95": 0.0, "percentile_99": 0.0,
        }

    q_vals = aligned["q"].values.copy()
    ret_vals = aligned["ret"].values

    # Actual Sharpe
    weights = np.array([alloc_map.get(int(q), 1.0) for q in q_vals])
    actual_port = ret_vals * weights
    actual_sharpe = _sharpe(pd.Series(actual_port))

    # Permutation loop
    rng = np.random.default_rng(seed=42)
    perm_sharpes = np.zeros(n_perms)

    for i in range(n_perms):
        shuffled_q = rng.permutation(q_vals)
        w = np.array([alloc_map.get(int(q), 1.0) for q in shuffled_q])
        perm_ret = ret_vals * w
        eq = np.cumprod(1 + perm_ret)
        years = len(eq) / 12
        if eq[-1] > 0 and years >= 0.5:
            ar = eq[-1] ** (1 / years) - 1
            av = perm_ret.std() * np.sqrt(12)
            perm_sharpes[i] = ar / av if av > 0 else 0
        else:
            perm_sharpes[i] = 0

    p_value = float(np.mean(perm_sharpes >= actual_sharpe))

    return {
        "actual_sharpe": actual_sharpe,
        "permuted_mean": round(float(perm_sharpes.mean()), 3),
        "permuted_std": round(float(perm_sharpes.std()), 3),
        "percentile_95": round(float(np.percentile(perm_sharpes, 95)), 3),
        "percentile_99": round(float(np.percentile(perm_sharpes, 99)), 3),
        "p_value": round(p_value, 4),
        "significant": p_value < 0.05,
    }


def _monte_carlo_delta_test(q_filtered, q_original, spy_returns, alloc_map,
                             n_perms=MC_N_PERMUTATIONS):
    """Test whether the Sharpe improvement from filtering is significant.

    Randomly reassigns which Q4/Q5 dates get overridden to Q3, preserving
    the number of overrides.  Compares the resulting Sharpe delta distribution
    to the actual delta.

    Returns:
        dict with actual_delta, p_value, significant
    """
    aligned = pd.DataFrame({
        "q_orig": q_original, "q_filt": q_filtered, "ret": spy_returns,
    }).dropna()

    if len(aligned) < 24:
        return {"actual_delta": 0.0, "p_value": 1.0, "significant": False}

    q_orig = aligned["q_orig"].values
    q_filt = aligned["q_filt"].values
    ret_vals = aligned["ret"].values

    # Identify where overrides happened and which indices are Q4/Q5
    override_mask = q_orig != q_filt
    n_overrides = int(override_mask.sum())
    q45_indices = np.where((q_orig == 4) | (q_orig == 5))[0]

    if n_overrides == 0 or len(q45_indices) == 0:
        return {"actual_delta": 0.0, "p_value": 1.0, "significant": False}

    # Actual delta
    w_orig = np.array([alloc_map.get(int(q), 1.0) for q in q_orig])
    w_filt = np.array([alloc_map.get(int(q), 1.0) for q in q_filt])
    sharpe_orig = _sharpe(pd.Series(ret_vals * w_orig))
    sharpe_filt = _sharpe(pd.Series(ret_vals * w_filt))
    actual_delta = sharpe_filt - sharpe_orig

    # Permutation: randomly choose which Q4/Q5 dates get overridden
    rng = np.random.default_rng(seed=42)
    perm_deltas = np.zeros(n_perms)

    n_to_pick = min(n_overrides, len(q45_indices))

    for i in range(n_perms):
        perm_q = q_orig.copy()
        chosen = rng.choice(q45_indices, size=n_to_pick, replace=False)
        perm_q[chosen] = 3
        w_perm = np.array([alloc_map.get(int(q), 1.0) for q in perm_q])
        perm_sharpe = _sharpe(pd.Series(ret_vals * w_perm))
        perm_deltas[i] = perm_sharpe - sharpe_orig

    p_value = float(np.mean(perm_deltas >= actual_delta))

    return {
        "actual_delta": round(actual_delta, 4),
        "p_value": round(p_value, 4),
        "significant": p_value < 0.05,
    }


def _build_recommendation(metrics, deltas, alpha_decomp, subperiod_sharpes,
                           filter_triggers, mc_results, phase2_winning):
    """Build recommendation with criterion-level reasoning.

    Evaluates each rule against multiple criteria and produces a
    recommendation with confidence level.

    Returns:
        dict with recommended_rule, confidence, criteria list, reasoning
    """
    rule_keys = ["rule_a", "rule_b", "rule_c"]
    nf = metrics.get("no_filter", {})

    rule_scores = {}

    for rule in rule_keys:
        rm = metrics.get(rule, {})
        if not rm:
            continue

        criteria = []
        score = 0

        # 1. Sharpe improvement
        delta_key = f"{rule}_vs_no_filter"
        d = deltas.get(delta_key, {})
        sharpe_d = d.get("sharpe", {}).get("value", 0)
        if sharpe_d > 0.05:
            criteria.append({
                "name": "Sharpe Improvement",
                "result": "pass",
                "detail": f"{rule} Sharpe {rm['sharpe']} vs No Filter {nf.get('sharpe', 0)} "
                          f"(+{sharpe_d:.2f})",
            })
            score += 2
        elif sharpe_d > 0:
            criteria.append({
                "name": "Sharpe Improvement",
                "result": "marginal",
                "detail": f"{rule} Sharpe {rm['sharpe']} vs No Filter {nf.get('sharpe', 0)} "
                          f"(+{sharpe_d:.2f}, marginal improvement)",
            })
            score += 1
        else:
            criteria.append({
                "name": "Sharpe Improvement",
                "result": "fail",
                "detail": f"{rule} Sharpe {rm['sharpe']} vs No Filter {nf.get('sharpe', 0)} "
                          f"({sharpe_d:+.2f}, no improvement)",
            })

        # 2. Drawdown reduction
        dd_d = d.get("max_drawdown", {}).get("value", 0)
        if dd_d > 2.0:  # >2pp improvement
            criteria.append({
                "name": "Drawdown Reduction",
                "result": "pass",
                "detail": f"Max drawdown improved by {dd_d:+.1f}pp "
                          f"({rm['max_drawdown']:.1f}% vs {nf.get('max_drawdown', 0):.1f}%)",
            })
            score += 2
        elif dd_d > 0:
            criteria.append({
                "name": "Drawdown Reduction",
                "result": "marginal",
                "detail": f"Max drawdown improved by {dd_d:+.1f}pp (marginal)",
            })
            score += 1
        else:
            criteria.append({
                "name": "Drawdown Reduction",
                "result": "fail",
                "detail": f"No drawdown improvement ({dd_d:+.1f}pp)",
            })

        # 3. Alpha significance
        alpha = alpha_decomp.get(rule, {})
        t_stat = alpha.get("t_stat", 0)
        alpha_pct = alpha.get("alpha_annual_pct", 0)
        if alpha.get("significant"):
            criteria.append({
                "name": "Alpha Significance",
                "result": "pass",
                "detail": f"CAPM alpha {alpha_pct:+.2f}% (t={t_stat:.2f}, significant)",
            })
            score += 2
        elif abs(t_stat) > 1.0:
            criteria.append({
                "name": "Alpha Significance",
                "result": "marginal",
                "detail": f"CAPM alpha {alpha_pct:+.2f}% (t={t_stat:.2f}, not significant at 5%)",
            })
            score += 1
        else:
            criteria.append({
                "name": "Alpha Significance",
                "result": "fail",
                "detail": f"CAPM alpha {alpha_pct:+.2f}% (t={t_stat:.2f}, weak)",
            })

        # 4. Subperiod consistency
        n_better = 0
        n_periods = 0
        for period, sharpes in subperiod_sharpes.items():
            rule_s = sharpes.get(rule)
            nf_s = sharpes.get("no_filter")
            if rule_s is not None and nf_s is not None:
                n_periods += 1
                if rule_s >= nf_s:
                    n_better += 1
        if n_periods > 0 and n_better / n_periods >= 0.6:
            criteria.append({
                "name": "Subperiod Consistency",
                "result": "pass",
                "detail": f"Sharpe >= No Filter in {n_better}/{n_periods} subperiods",
            })
            score += 2
        elif n_periods > 0 and n_better / n_periods >= 0.4:
            criteria.append({
                "name": "Subperiod Consistency",
                "result": "marginal",
                "detail": f"Sharpe >= No Filter in {n_better}/{n_periods} subperiods",
            })
            score += 1
        else:
            criteria.append({
                "name": "Subperiod Consistency",
                "result": "fail",
                "detail": f"Sharpe >= No Filter in only {n_better}/{n_periods} subperiods",
            })

        # 5. Filter accuracy
        triggers = filter_triggers.get(rule, [])
        n_correct = sum(1 for t in triggers if t.get("was_correct"))
        n_assessed = sum(1 for t in triggers if t.get("was_correct") is not None)
        accuracy = n_correct / n_assessed * 100 if n_assessed > 0 else 0
        if accuracy > 55:
            criteria.append({
                "name": "Filter Accuracy",
                "result": "pass",
                "detail": f"{accuracy:.0f}% of triggers preceded negative 3m SPY returns "
                          f"({n_correct}/{n_assessed})",
            })
            score += 2
        elif accuracy > 45:
            criteria.append({
                "name": "Filter Accuracy",
                "result": "marginal",
                "detail": f"{accuracy:.0f}% trigger accuracy ({n_correct}/{n_assessed}) "
                          f"— near coin-flip",
            })
            score += 1
        else:
            criteria.append({
                "name": "Filter Accuracy",
                "result": "fail",
                "detail": f"{accuracy:.0f}% trigger accuracy ({n_correct}/{n_assessed}) "
                          f"— below coin-flip",
            })

        # 6. Monte Carlo p-value for delta
        mc_delta = mc_results.get("delta_tests", {}).get(f"{rule}_vs_no_filter", {})
        mc_p = mc_delta.get("p_value", 1.0)
        if mc_p < 0.05:
            criteria.append({
                "name": "Monte Carlo Significance",
                "result": "pass",
                "detail": f"Sharpe improvement p={mc_p:.3f} (significant at 5%)",
            })
            score += 2
        elif mc_p < 0.15:
            criteria.append({
                "name": "Monte Carlo Significance",
                "result": "marginal",
                "detail": f"Sharpe improvement p={mc_p:.3f} (suggestive but not significant)",
            })
            score += 1
        else:
            criteria.append({
                "name": "Monte Carlo Significance",
                "result": "fail",
                "detail": f"Sharpe improvement p={mc_p:.3f} (not significant)",
            })

        rule_scores[rule] = {"score": score, "criteria": criteria}

    # Pick the best rule
    if not rule_scores:
        return {
            "recommended_rule": "no_filter",
            "confidence": "low",
            "criteria": [],
            "reasoning": "No filter rules could be evaluated.",
        }

    best_rule = max(rule_scores, key=lambda k: rule_scores[k]["score"])
    best_score = rule_scores[best_rule]["score"]
    best_criteria = rule_scores[best_rule]["criteria"]

    # Confidence: 0-4 low, 5-8 moderate, 9-12 high
    if best_score >= 9:
        confidence = "high"
    elif best_score >= 5:
        confidence = "moderate"
    else:
        confidence = "low"

    # If best score is too low, recommend no filter
    if best_score < 3:
        best_rule = "no_filter"
        confidence = "low"

    # Build reasoning summary
    n_pass = sum(1 for c in best_criteria if c["result"] == "pass")
    n_marginal = sum(1 for c in best_criteria if c["result"] == "marginal")
    n_fail = sum(1 for c in best_criteria if c["result"] == "fail")

    if best_rule == "no_filter":
        reasoning = (
            f"No filter rule meets minimum criteria. Best candidate scored "
            f"{best_score}/12 ({n_pass} pass, {n_marginal} marginal, {n_fail} fail). "
            f"Recommend retaining the unfiltered production signal."
        )
    else:
        label = VARIANT_LABELS.get(best_rule, best_rule)
        p2_match = " (matches Phase 2 winner)" if best_rule == phase2_winning else ""
        reasoning = (
            f"{label}{p2_match} scores {best_score}/12 across 6 criteria "
            f"({n_pass} pass, {n_marginal} marginal, {n_fail} fail). "
        )
        # Add specific highlights
        passes = [c["name"] for c in best_criteria if c["result"] == "pass"]
        if passes:
            reasoning += f"Strengths: {', '.join(passes)}. "
        fails = [c["name"] for c in best_criteria if c["result"] == "fail"]
        if fails:
            reasoning += f"Weaknesses: {', '.join(fails)}."

    return {
        "recommended_rule": best_rule,
        "confidence": confidence,
        "criteria": best_criteria,
        "reasoning": reasoning.strip(),
        "all_scores": {k: v["score"] for k, v in rule_scores.items()},
    }


# ---------------------------------------------------------------------------
# Full Phase 3 backtest (3A.1 + 3A.2 + 3A.3)
# ---------------------------------------------------------------------------

def run_phase3_backtest(phase2_result, gli_data, spy_daily):
    """Run the complete Phase 3 backtest.

    Combines all three layers:
      3A.1: equity_curves, metrics, deltas, subperiod_sharpes, alpha_decomp
      3A.2: crash_detection, drawdowns, rule filter triggers
      3A.3: monte_carlo, recommendation

    Args:
        phase2_result: dict from run_phase2_analysis()
        gli_data: dict from build_gli_signal() with 'quintiles' pd.Series
        spy_daily: pd.Series of daily SPY close prices

    Returns:
        Full backtest result dict (see schema in module docstring)
    """
    # Run 3A.1 + 3A.2
    result = run_phase3_backtest_with_drawdowns(phase2_result, gli_data, spy_daily)
    if "error" in result:
        return result

    internals = result.pop("_internals", {})
    sims = internals.get("sims", {})
    spy_returns = internals.get("spy_returns", pd.Series(dtype=float))
    filtered_signals = internals.get("filtered_signals", {})

    alloc_map = ALLOC_MAP

    # ── 13. Monte Carlo permutation tests ────────────────────────────────
    print(f"[PHASE3] Running Monte Carlo ({MC_N_PERMUTATIONS} permutations)...")
    mc_variants = {}
    for name, sim in sims.items():
        if sim:
            mc_variants[name] = _monte_carlo_sharpe_test(
                sim["quintiles"], spy_returns, alloc_map
            )
            print(f"[PHASE3] MC {name}: p={mc_variants[name]['p_value']}")

    mc_delta_tests = {}
    nf_sim = sims.get("no_filter")
    if nf_sim:
        for rule_name in ["rule_a", "rule_b", "rule_c"]:
            rule_sim = sims.get(rule_name)
            if rule_sim:
                mc_delta_tests[f"{rule_name}_vs_no_filter"] = _monte_carlo_delta_test(
                    rule_sim["quintiles"], nf_sim["quintiles"],
                    spy_returns, alloc_map,
                )

    result["monte_carlo"] = {
        "n_permutations": MC_N_PERMUTATIONS,
        "variants": mc_variants,
        "delta_tests": mc_delta_tests,
    }
    print("[PHASE3] Monte Carlo complete.")

    # ── 14. Recommendation ───────────────────────────────────────────────
    print("[PHASE3] Building recommendation...")
    filter_triggers = {}
    for rule_name in ["rule_a", "rule_b", "rule_c"]:
        filter_triggers[rule_name] = result.get(f"{rule_name}_filter_triggers", [])

    result["recommendation"] = _build_recommendation(
        metrics=result["metrics"],
        deltas=result["deltas"],
        alpha_decomp=result["alpha_decomp"],
        subperiod_sharpes=result["subperiod_sharpes"],
        filter_triggers=filter_triggers,
        mc_results=result["monte_carlo"],
        phase2_winning=phase2_result.get("winning_rule", "rule_a"),
    )

    print(f"[PHASE3] Recommendation: {result['recommendation']['recommended_rule']} "
          f"(confidence: {result['recommendation']['confidence']})")
    print("[PHASE3] Full Phase 3 backtest complete.")
    return result
