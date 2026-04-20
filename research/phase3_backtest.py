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

# Phase 3.5 — Sensitivity grid thresholds
SENSITIVITY_PCTL = [5, 10, 15, 20, 25, 30, 35]
SENSITIVITY_CHG = [-10, 0, 10, 20, 30, 40, 50]

COVID_PRESERVE_DATES = [
    "2020-02-01", "2020-03-01", "2020-04-01",
    "2020-05-01", "2020-06-01",
]


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


def _align_rf(rets, rf):
    """Align a monthly rf series to `rets`, ffill-then-zero on gaps."""
    if rf is None:
        return pd.Series(0.0, index=rets.index)
    rf_aligned = rf.reindex(rets.index, method="ffill").fillna(0.0)
    return rf_aligned


def _sharpe(rets, rf=None):
    """Sharpe ratio = mean(excess) / std(excess) * sqrt(12).

    Arithmetic mean of monthly excess returns (strategy - rf). Annualization
    by sqrt(12). Falls back to rf=0 if no rf series provided.
    """
    if len(rets) < 12:
        return 0.0
    rf_m = _align_rf(rets, rf)
    excess = rets - rf_m
    sd = float(excess.std())
    if sd <= 1e-12:
        return 0.0
    return round(float(excess.mean()) / sd * float(np.sqrt(12)), 3)


def _sortino(rets, rf=None, mar=0.0):
    """Sortino ratio = mean(excess) * 12 / downside_dev(excess) (annualized).

    Uses arithmetic mean of excess returns in the numerator. Downside
    deviation is sqrt(mean(min(excess,0)^2)) * sqrt(12).
    """
    if len(rets) < 12:
        return 0.0
    rf_m = _align_rf(rets, rf)
    excess = rets - rf_m - mar / 12.0
    downside = excess.clip(upper=0)
    downside_dev = float(np.sqrt((downside ** 2).mean()) * np.sqrt(12))
    if downside_dev <= 1e-12:
        return 0.0
    return round(float(excess.mean()) * 12.0 / downside_dev, 3)


def _calmar(rets):
    """Calmar ratio from monthly returns."""
    eq = (1 + rets).cumprod()
    ar = _ann_ret(eq)
    dd = abs(_max_dd(eq))
    return round(ar / dd, 2) if dd > 0.001 else 0.0


def _load_rf_monthly():
    """Load Fama-French monthly RF series (decimal, month-start index).

    Returns an empty Series if FF data cannot be loaded; callers then treat
    the cash leg as earning 0% (equivalent to pre-fix behavior).
    """
    try:
        from research.ff_factor_data import load_ff_factors
        ff = load_ff_factors()
        if ff is None or "RF" not in ff.columns:
            return pd.Series(dtype=float)
        rf = ff["RF"].copy()
        rf.index = pd.to_datetime(rf.index).to_period("M").to_timestamp()
        return rf.groupby(level=0).last().sort_index()
    except Exception as e:
        print(f"[PHASE3] Warning: could not load FF RF series ({e}); using rf=0")
        return pd.Series(dtype=float)


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


def _simulate_variant(quintiles, spy_returns, alloc_map, rf_monthly=None):
    """Simulate equity curve for one variant.

    Args:
        quintiles: pd.Series of Q1-Q5 (DatetimeIndex, month-start)
        spy_returns: pd.Series of monthly SPY returns (DatetimeIndex)
        alloc_map: dict {quintile_int: weight_float}
        rf_monthly: pd.Series of monthly risk-free rate (decimal); cash leg
            earns rf on the unallocated `(1 - weight)` portion. If None,
            cash leg earns 0%.

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
    rf_m = _align_rf(aligned["spy_ret"], rf_monthly)
    port_ret = aligned["spy_ret"] * weights + rf_m * (1 - weights)
    port_eq = (1 + port_ret).cumprod()

    return {
        "equity": port_eq,
        "returns": port_ret,
        "weights": weights,
        "quintiles": aligned["quintile"],
        "rf": rf_m,
    }


def _compute_metrics(sim, rf_monthly=None):
    """Compute performance metrics from a simulation result."""
    if sim is None:
        return None

    eq = sim["equity"]
    rets = sim["returns"]
    rf = rf_monthly if rf_monthly is not None else sim.get("rf")

    return {
        "total_return": round(float(eq.iloc[-1] - 1) * 100, 1),
        "annualized_return": round(_ann_ret(eq) * 100, 2),
        "annualized_vol": round(_ann_vol(rets) * 100, 2),
        "sharpe": _sharpe(rets, rf),
        "sortino": _sortino(rets, rf),
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


def _compute_subperiod_sharpes(returns_dict, subperiods, rf_monthly=None):
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
                period_sharpes[variant] = _sharpe(period_rets, rf_monthly)
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
# Multi-factor alpha (Fama-French 5 + Momentum)
# ---------------------------------------------------------------------------

_FF_FACTORS_CACHE = {"df": None, "loaded": False}


def _get_ff_factors():
    """Load FF5 + Momentum factor data, memoized in-process."""
    if _FF_FACTORS_CACHE["loaded"]:
        return _FF_FACTORS_CACHE["df"]
    try:
        from research.ff_factor_data import load_ff_factors
        df = load_ff_factors()
        _FF_FACTORS_CACHE["df"] = df
        _FF_FACTORS_CACHE["loaded"] = True
        return df
    except Exception as e:
        print(f"[FF5] Factor load failed: {e}")
        _FF_FACTORS_CACHE["loaded"] = True
        _FF_FACTORS_CACHE["df"] = None
        return None


def _run_ols_hac(y, X, lags=3):
    """Run OLS with Newey-West HAC standard errors.

    Returns dict with alpha, factor betas/tstats/pvalues, R², adj R², DW.
    """
    import statsmodels.api as sm
    from statsmodels.stats.stattools import durbin_watson

    X_with_const = sm.add_constant(X, has_constant="add")
    model = sm.OLS(y, X_with_const, missing="drop")
    results = model.fit(cov_type="HAC", cov_kwds={"maxlags": lags})

    alpha_monthly = float(results.params.iloc[0])
    alpha_tstat = float(results.tvalues.iloc[0])
    alpha_pvalue = float(results.pvalues.iloc[0])

    factor_loadings = {}
    for i, name in enumerate(X.columns):
        factor_loadings[name] = {
            "beta": round(float(results.params.iloc[i + 1]), 4),
            "tstat": round(float(results.tvalues.iloc[i + 1]), 3),
            "pvalue": round(float(results.pvalues.iloc[i + 1]), 4),
        }

    try:
        dw = float(durbin_watson(results.resid))
    except Exception:
        dw = None

    # Annualize alpha via compounding
    alpha_annual = (1 + alpha_monthly) ** 12 - 1

    return {
        "alpha_monthly_pct": round(alpha_monthly * 100, 4),
        "alpha_annual_pct": round(alpha_annual * 100, 2),
        "alpha_tstat": round(alpha_tstat, 3),
        "alpha_pvalue": round(alpha_pvalue, 4),
        "r_squared": round(float(results.rsquared), 4),
        "adj_r_squared": round(float(results.rsquared_adj), 4),
        "factor_loadings": factor_loadings,
        "n_observations": int(results.nobs),
        "durbin_watson": round(dw, 3) if dw is not None else None,
        "significant": abs(alpha_tstat) > 2.0,
    }


def compute_ff5_mom_alpha(strategy_returns):
    """Run CAPM, FF3+Mom, and FF5+Mom regressions.

    Args:
        strategy_returns: pd.Series of monthly strategy returns (decimals),
                         indexed by dates

    Returns:
        dict with models (capm, ff3_mom, ff5_mom), comparison, and metadata
    """
    null_result = {
        "error": "FF factor data unavailable",
        "models": None,
        "comparison": None,
    }

    ff = _get_ff_factors()
    if ff is None or len(ff) == 0:
        return null_result

    # Normalize index to month-start for alignment
    strat = strategy_returns.copy()
    strat.index = pd.to_datetime(strat.index).to_period("M").to_timestamp()
    strat = strat.groupby(level=0).last().dropna()

    ff_idx = ff.index.to_period("M").to_timestamp()
    ff2 = ff.copy()
    ff2.index = ff_idx

    aligned = pd.DataFrame({"strat": strat}).join(ff2, how="inner").dropna()
    if len(aligned) < 24:
        return {"error": f"Insufficient overlap: {len(aligned)} months"}

    excess = aligned["strat"] - aligned["RF"]

    # CAPM: excess ~ Mkt-RF
    X_capm = aligned[["Mkt-RF"]].rename(columns={"Mkt-RF": "MKT"})
    try:
        capm = _run_ols_hac(excess, X_capm, lags=3)
    except Exception as e:
        return {"error": f"CAPM regression failed: {e}"}

    # FF3 + Momentum: excess ~ Mkt-RF + SMB + HML + Mom
    X_ff3m = aligned[["Mkt-RF", "SMB", "HML", "Mom"]].rename(
        columns={"Mkt-RF": "MKT", "Mom": "MOM"}
    )
    try:
        ff3_mom = _run_ols_hac(excess, X_ff3m, lags=3)
    except Exception as e:
        ff3_mom = {"error": str(e)}

    # FF5 + Momentum: excess ~ Mkt-RF + SMB + HML + RMW + CMA + Mom
    X_ff5m = aligned[["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]].rename(
        columns={"Mkt-RF": "MKT", "Mom": "MOM"}
    )
    try:
        ff5_mom = _run_ols_hac(excess, X_ff5m, lags=3)
    except Exception as e:
        ff5_mom = {"error": str(e)}

    capm_alpha = capm.get("alpha_annual_pct", 0)
    ff5_alpha = ff5_mom.get("alpha_annual_pct", 0) if "error" not in ff5_mom else capm_alpha
    absorbed_pct = 0.0
    if abs(capm_alpha) > 0.01:
        absorbed_pct = round((capm_alpha - ff5_alpha) / capm_alpha * 100, 1)

    comparison = {
        "capm_alpha": capm_alpha,
        "ff3_mom_alpha": ff3_mom.get("alpha_annual_pct") if "error" not in ff3_mom else None,
        "ff5_mom_alpha": ff5_alpha if "error" not in ff5_mom else None,
        "alpha_absorbed_pct": absorbed_pct,
    }

    return {
        "models": {
            "capm": capm,
            "ff3_mom": ff3_mom,
            "ff5_mom": ff5_mom,
        },
        "comparison": comparison,
        "date_range": [
            aligned.index[0].strftime("%Y-%m-%d"),
            aligned.index[-1].strftime("%Y-%m-%d"),
        ],
        "hac_lags": 3,
    }


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


def _compute_filter_accuracy_reframed(filtered_signals_list, phase1_dataset):
    """Reframed filter accuracy using label_moderate_tp from Phase 1.

    Evaluates across ALL Q4/Q5 signals (not just triggered ones):
      - TRUE NEGATIVE: filter triggered on a false positive (good)
      - TRUE POSITIVE: filter preserved a true positive (good)
      - FALSE NEGATIVE: filter missed a false positive (bad)
      - TYPE II ERROR: filter triggered on a true positive (bad)

    Args:
        filtered_signals_list: list of dicts from Phase 2 filtered_signals
        phase1_dataset: list of dicts from Phase 1 full_dataset (has label_moderate_tp)

    Returns:
        dict with counts, accuracy, precision, recall, f1, per-signal details
    """
    # Build lookup: signal_date -> label_moderate_tp
    label_lookup = {}
    for row in phase1_dataset:
        dt = row.get("signal_date")
        label = row.get("label_moderate_tp")
        if dt is not None and label is not None and not (isinstance(label, float) and np.isnan(label)):
            label_lookup[dt] = int(label)

    # Build lookup: signal_date -> filter_triggered
    trigger_lookup = {}
    for row in filtered_signals_list:
        dt = row.get("signal_date")
        trigger_lookup[dt] = bool(row.get("filter_triggered", False))

    true_negatives = []   # correctly filtered FPs
    true_positives = []   # correctly preserved TPs
    false_negatives = []  # missed FPs (should have been filtered)
    type_ii_errors = []   # over-filtered TPs

    # Evaluate ALL signals that appear in the Phase 2 filtered_signals
    for row in filtered_signals_list:
        dt = row.get("signal_date")
        is_tp = label_lookup.get(dt)
        triggered = bool(row.get("filter_triggered", False))

        if is_tp is None:
            continue  # no label available

        entry = {"date": dt, "is_tp": bool(is_tp), "filter_triggered": triggered}

        if triggered and is_tp == 0:
            true_negatives.append(entry)
        elif not triggered and is_tp == 1:
            true_positives.append(entry)
        elif not triggered and is_tp == 0:
            false_negatives.append(entry)
        elif triggered and is_tp == 1:
            type_ii_errors.append(entry)

    tn = len(true_negatives)
    tp = len(true_positives)
    fn = len(false_negatives)
    t2 = len(type_ii_errors)
    total = tn + tp + fn + t2

    overall_accuracy = round((tn + tp) / total, 3) if total > 0 else 0
    precision = round(tn / (tn + t2), 3) if (tn + t2) > 0 else 0
    recall = round(tn / (tn + fn), 3) if (tn + fn) > 0 else 0
    f1 = round(2 * precision * recall / (precision + recall), 3) if (precision + recall) > 0 else 0

    return {
        "true_negatives": tn,
        "true_positives": tp,
        "false_negatives": fn,
        "type_ii_errors": t2,
        "overall_accuracy": overall_accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "total_signals": total,
    }


def _build_filter_triggers(filtered_signals_list, spy_returns, phase1_dataset=None):
    """Build detailed filter trigger analysis for a rule.

    For each date the filter triggered, compute forward SPY returns and
    use label_moderate_tp (if available) for correctness assessment.

    Args:
        filtered_signals_list: list of dicts from Phase 2 filtered_signals
        spy_returns: pd.Series of monthly SPY returns
        phase1_dataset: optional list of dicts with label_moderate_tp

    Returns:
        list of trigger dicts with forward returns and correctness assessment
    """
    # Build TP label lookup from Phase 1 data
    label_lookup = {}
    if phase1_dataset:
        for row in phase1_dataset:
            dt = row.get("signal_date")
            label = row.get("label_moderate_tp")
            if dt is not None and label is not None and not (isinstance(label, float) and np.isnan(label)):
                label_lookup[dt] = int(label)

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
            end_3m = min(dt_pos + 3, len(idx))
            if end_3m > dt_pos:
                fwd_3m = round(float((1 + spy_returns.iloc[dt_pos:end_3m]).prod() - 1) * 100, 2)

            end_6m = min(dt_pos + 6, len(idx))
            if end_6m > dt_pos:
                fwd_6m = round(float((1 + spy_returns.iloc[dt_pos:end_6m]).prod() - 1) * 100, 2)

        # Use label_moderate_tp for correctness (is_tp=0 means filter was correct)
        is_tp = label_lookup.get(date_str)
        if is_tp is not None:
            was_correct = is_tp == 0  # Correct = filtered a false positive
        elif fwd_3m is not None:
            was_correct = fwd_3m < 0  # Fallback to old logic
        else:
            was_correct = None

        triggers.append({
            "date": date_str,
            "original_quintile": row["original_quintile"],
            "filtered_quintile": row["filtered_quintile"],
            "fwd_3m_spy_return": fwd_3m,
            "fwd_6m_spy_return": fwd_6m,
            "was_correct": was_correct,
            "is_tp": is_tp,
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

    # Load Fama-French RF series once and align to the backtest window.
    # Used for the cash-leg return and for the arithmetic-excess Sharpe/Sortino.
    rf_full = _load_rf_monthly()
    rf_monthly = rf_full.reindex(common_idx, method="ffill").fillna(0.0) if len(rf_full) > 0 else pd.Series(0.0, index=common_idx)
    if len(rf_full) > 0:
        print(f"[PHASE3] RF aligned: {rf_monthly.iloc[0]*12*100:.2f}% to {rf_monthly.iloc[-1]*12*100:.2f}% (annualized)")
    else:
        print("[PHASE3] RF series unavailable; cash leg earns 0% (pre-fix behavior)")

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
        sims[name] = _simulate_variant(quints, spy_returns, alloc_map, rf_monthly=rf_monthly)
        if sims[name]:
            print(f"[PHASE3] {name}: {len(sims[name]['equity'])} months simulated")

    # Buy-and-hold baseline (100% SPY, no cash leg; rf still used for Sharpe excess)
    bh_returns = spy_returns.dropna()
    bh_equity = (1 + bh_returns).cumprod()
    bh_metrics = {
        "total_return": round(float(bh_equity.iloc[-1] - 1) * 100, 1),
        "annualized_return": round(_ann_ret(bh_equity) * 100, 2),
        "annualized_vol": round(_ann_vol(bh_returns) * 100, 2),
        "sharpe": _sharpe(bh_returns, rf_monthly),
        "sortino": _sortino(bh_returns, rf_monthly),
        "max_drawdown": round(_max_dd(bh_equity) * 100, 1),
        "calmar": _calmar(bh_returns),
    }

    # ── 4. Compute metrics ───────────────────────────────────────────────
    metrics = {}
    for name, sim in sims.items():
        metrics[name] = _compute_metrics(sim, rf_monthly=rf_monthly)
    metrics["buyhold"] = bh_metrics

    # ── 4a. Verification: old-formula Sharpe/Sortino for comparison ──────
    # Old formula: geometric annualized return / annualized std (no rf).
    # Printed here so the audit-fix delta is visible in refresh logs.
    def _old_sharpe(rets):
        if len(rets) < 12:
            return 0.0
        eq = (1 + rets).cumprod()
        yrs = len(eq) / 12
        if eq.iloc[-1] <= 0 or yrs < 0.5:
            return 0.0
        ar = float(eq.iloc[-1] ** (1 / yrs) - 1)
        av = float(rets.std() * np.sqrt(12))
        return round(ar / av, 3) if av > 0 else 0.0

    def _old_sortino(rets):
        if len(rets) < 12:
            return 0.0
        downside = rets.clip(upper=0)
        dd = float(np.sqrt((downside ** 2).mean()) * np.sqrt(12))
        eq = (1 + rets).cumprod()
        yrs = len(eq) / 12
        if eq.iloc[-1] <= 0 or yrs < 0.5:
            return 0.0
        ar = float(eq.iloc[-1] ** (1 / yrs) - 1)
        return round(ar / dd, 3) if dd > 0 else 0.0

    print("[PHASE3] SHARPE/SORTINO CORRECTION COMPARISON")
    print("[PHASE3]   Variant         | Sharpe old -> new  |  Sortino old -> new")
    for name, sim in list(sims.items()) + [("buyhold", {"returns": bh_returns})]:
        if sim is None:
            continue
        r = sim["returns"] if isinstance(sim, dict) else sim
        s_old, s_new = _old_sharpe(r), _sharpe(r, rf_monthly)
        so_old, so_new = _old_sortino(r), _sortino(r, rf_monthly)
        print(f"[PHASE3]   {name:<15} | {s_old:>6.3f} -> {s_new:>6.3f}   |  {so_old:>6.3f} -> {so_new:>6.3f}")

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

    subperiod_sharpes = _compute_subperiod_sharpes(returns_dict, SUBPERIODS, rf_monthly=rf_monthly)

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

    # ── Sharpe attribution: quintile-method × Sharpe-formula decomposition ──
    # Published 1.38 Sharpe used (old formula + full-sample qcut). Today's
    # dashboard reads 0.91 (new formula + expanding-window). This 2×2 table
    # separates how much of the gap comes from each change. All four rows
    # use the SAME strategy returns (SPY * w + rf * (1-w)), SAME data window,
    # SAME allocation rule — only quintile method and Sharpe formula vary.
    try:
        signal_for_decomp = gli_data.get("signal")
        if signal_for_decomp is None:
            # Rebuild from quintiles index if signal isn't present — at least
            # we have the expanding quintiles straight from gli_data.
            raise RuntimeError("gli_data['signal'] missing — cannot compute full-sample quintile variant")

        # Align signal + spy + rf to a common window
        decomp_idx = signal_for_decomp.dropna().index.intersection(spy_returns.index)
        sig_aligned = signal_for_decomp.reindex(decomp_idx)
        ret_aligned = spy_returns.reindex(decomp_idx)
        rf_aligned = rf_monthly.reindex(decomp_idx, method="ffill").fillna(0.0)

        # Quintile series A: FULL-SAMPLE (pd.qcut on the entire signal)
        q_full = pd.qcut(sig_aligned, 5, labels=[1, 2, 3, 4, 5], duplicates='drop').astype(float)

        # Quintile series B: EXPANDING-WINDOW (matches data_loaders.py + today's
        # backtest_engine production path). 36-month warmup.
        q_exp = pd.Series(np.nan, index=decomp_idx, dtype=float)
        vals = sig_aligned.values
        for i in range(36, len(sig_aligned)):
            hist = vals[:i + 1]
            curr = vals[i]
            pct = float((hist < curr).sum()) / len(hist) * 100
            q_exp.iloc[i] = (1 if pct < 20 else 2 if pct < 40 else
                             3 if pct < 60 else 4 if pct < 80 else 5)

        def _port_rets(q_series):
            """SPY * w + rf * (1-w) given a 1-based quintile series."""
            aligned = pd.concat([q_series.rename("q"), ret_aligned.rename("r"),
                                 rf_aligned.rename("rf")], axis=1).dropna()
            if len(aligned) < 12:
                return None
            w = aligned["q"].map(alloc_map).astype(float)
            return aligned["r"] * w + aligned["rf"] * (1 - w), aligned["rf"]

        def _old_sharpe(rets):
            """Pre-audit formula: geometric annualized return / annualized vol.
            No rf subtraction. This is what produced the published 1.38."""
            if rets is None or len(rets) < 12:
                return None
            eq = (1 + rets).cumprod()
            yrs = len(rets) / 12
            if eq.iloc[-1] <= 0 or yrs < 0.5:
                return None
            ar = float(eq.iloc[-1] ** (1 / yrs) - 1)
            av = float(rets.std() * np.sqrt(12))
            return round(ar / av, 3) if av > 0 else None

        def _new_sharpe(rets, rf):
            """Post-audit formula: mean(excess) / std(excess) * sqrt(12)."""
            if rets is None or len(rets) < 12:
                return None
            excess = rets - rf.reindex(rets.index).fillna(0.0)
            sd = float(excess.std())
            if sd <= 1e-12:
                return None
            return round(float(excess.mean()) / sd * float(np.sqrt(12)), 3)

        # Compute four scenarios
        pr_full_result = _port_rets(q_full)
        pr_exp_result = _port_rets(q_exp)

        scenarios = {}
        if pr_full_result is not None:
            pr_full, rf_full_al = pr_full_result
            scenarios["full_old"] = _old_sharpe(pr_full)
            scenarios["full_new"] = _new_sharpe(pr_full, rf_full_al)
            scenarios["full_n"] = len(pr_full)
            scenarios["full_ann_ret_geom"] = round((pr_full.add(1).prod()) ** (12 / len(pr_full)) * 100 - 100, 2)
            scenarios["full_ann_vol"] = round(float(pr_full.std()) * float(np.sqrt(12)) * 100, 2)
        if pr_exp_result is not None:
            pr_exp, rf_exp_al = pr_exp_result
            scenarios["exp_old"] = _old_sharpe(pr_exp)
            scenarios["exp_new"] = _new_sharpe(pr_exp, rf_exp_al)
            scenarios["exp_n"] = len(pr_exp)
            scenarios["exp_ann_ret_geom"] = round((pr_exp.add(1).prod()) ** (12 / len(pr_exp)) * 100 - 100, 2)
            scenarios["exp_ann_vol"] = round(float(pr_exp.std()) * float(np.sqrt(12)) * 100, 2)

        print("[PHASE3] ═══════════════════════════════════════════════════════════════")
        print("[PHASE3] SHARPE DECOMPOSITION — quintile method × Sharpe formula")
        print("[PHASE3]   Strategy: SPY * w + rf * (1-w), Q1-Q3=100%, Q4-Q5=10%, no filter")
        print("[PHASE3]   Data:     same window, same SPY, same RF series across all 4 cells")
        print("[PHASE3] ───────────────────────────────────────────────────────────────")
        print("[PHASE3]                         | Old formula   | New formula ")
        print("[PHASE3]                         | (geom / vol,  | (mean excess /")
        print("[PHASE3]                         |  no rf subtr.)|  std excess)")
        print("[PHASE3] ───────────────────────────────────────────────────────────────")
        def _fmt(v):
            return f"{v:.3f}" if isinstance(v, (int, float)) else "n/a"
        print(f"[PHASE3] Full-sample quintiles   | {_fmt(scenarios.get('full_old')):>13} | {_fmt(scenarios.get('full_new')):>13}")
        print(f"[PHASE3] Expanding-window quint  | {_fmt(scenarios.get('exp_old')):>13} | {_fmt(scenarios.get('exp_new')):>13}")
        print("[PHASE3] ───────────────────────────────────────────────────────────────")
        print(f"[PHASE3] Ancillary stats (full-sample):    N={scenarios.get('full_n')}  ann_ret_geom={scenarios.get('full_ann_ret_geom')}%  ann_vol={scenarios.get('full_ann_vol')}%")
        print(f"[PHASE3] Ancillary stats (expanding):       N={scenarios.get('exp_n')}  ann_ret_geom={scenarios.get('exp_ann_ret_geom')}%  ann_vol={scenarios.get('exp_ann_vol')}%")
        print("[PHASE3] ───────────────────────────────────────────────────────────────")
        fo, fn = scenarios.get("full_old"), scenarios.get("full_new")
        eo, en = scenarios.get("exp_old"), scenarios.get("exp_new")
        if all(x is not None for x in (fo, fn, eo, en)):
            formula_gap = round(fo - fn, 3)
            quintile_gap = round(fn - en, 3)
            total_gap = round(fo - en, 3)
            print(f"[PHASE3] Attribution (Old full-sample → New expanding):")
            print(f"[PHASE3]   Formula change (Old → New) at full-sample:  Δ = {-formula_gap:+.3f}")
            print(f"[PHASE3]   Quintile change (Full → Expanding) at New:  Δ = {-quintile_gap:+.3f}")
            print(f"[PHASE3]   Total attributable gap:                      Δ = {-total_gap:+.3f}")
            print(f"[PHASE3]   Published reference (old formula + full-sample): {fo}")
            print(f"[PHASE3]   Dashboard reading (new formula + expanding):     {en}")
        print("[PHASE3] ═══════════════════════════════════════════════════════════════")
    except Exception as _decomp_err:
        print(f"[PHASE3] Sharpe decomposition diagnostic failed: {_decomp_err}")

    # ── Alt-allocation diagnostic: Q5-only defensive vs Q4-Q5 defensive ──
    # In current data mom6 Q4 has averaged +7%/85% hit — NOT defensive
    # behavior. Test whether {1:100%, 2:100%, 3:100%, 4:100%, 5:10%} (only
    # Q5 defensive) produces better risk-adjusted returns than the current
    # production {Q4-Q5 = 10%}. Same signal, same filter path, same data —
    # only the allocation weight for Q4 changes.
    try:
        alt_alloc_map = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.1}
        # Compare on the no_filter raw-mom6 quintile series — purest read
        # on what the allocation rule itself does, independent of Rule A.
        nf_quints = variant_quintiles.get("no_filter")
        if nf_quints is not None:
            alt_sim = _simulate_variant(nf_quints, spy_returns, alt_alloc_map, rf_monthly=rf_monthly)
            if alt_sim is not None:
                alt_m = _compute_metrics(alt_sim, rf_monthly=rf_monthly)
                # Also Rule A filtered, for completeness
                ra_quints = variant_quintiles.get("rule_a")
                alt_ra_m = None
                if ra_quints is not None:
                    alt_ra_sim = _simulate_variant(ra_quints, spy_returns, alt_alloc_map, rf_monthly=rf_monthly)
                    if alt_ra_sim is not None:
                        alt_ra_m = _compute_metrics(alt_ra_sim, rf_monthly=rf_monthly)

                prod_nf = metrics.get("no_filter", {}) or {}
                prod_ra = metrics.get("rule_a", {}) or {}
                bh_m = metrics.get("buyhold", {}) or {}

                def _mfmt(v, suf=""):
                    return f"{v:>7.2f}{suf}" if isinstance(v, (int, float)) else f"{'n/a':>8}"

                print("[PHASE3] ═══════════════════════════════════════════════════════════════")
                print("[PHASE3] ALT-ALLOCATION DIAGNOSTIC — Q5-only defensive")
                print("[PHASE3]   Production:   {1:100, 2:100, 3:100, 4: 10, 5: 10}   (Q4-Q5 defensive)")
                print("[PHASE3]   Alternative:  {1:100, 2:100, 3:100, 4:100, 5: 10}   (Q5-only defensive)")
                print("[PHASE3]   Rationale: current-regime Q4 avg 6M = +7%/85% hit — not defensive behavior")
                print("[PHASE3] ───────────────────────────────────────────────────────────────")
                print("[PHASE3]                    |  Production  |  Alternative  |  SPY B&H")
                print("[PHASE3]                    |  Q4-Q5 def   |  Q5-only def  |")
                print("[PHASE3] ───────────────────────────────────────────────────────────────")
                print("[PHASE3]   NO FILTER variant:")
                print(f"[PHASE3]   Total Return       | {_mfmt(prod_nf.get('total_return'), '%')}    | {_mfmt(alt_m.get('total_return'), '%')}     | {_mfmt(bh_m.get('total_return'), '%')}")
                print(f"[PHASE3]   Annual Return      | {_mfmt(prod_nf.get('annualized_return'), '%')}    | {_mfmt(alt_m.get('annualized_return'), '%')}     | {_mfmt(bh_m.get('annualized_return'), '%')}")
                print(f"[PHASE3]   Sharpe             | {_mfmt(prod_nf.get('sharpe'))}     | {_mfmt(alt_m.get('sharpe'))}      | {_mfmt(bh_m.get('sharpe'))}")
                print(f"[PHASE3]   Sortino            | {_mfmt(prod_nf.get('sortino'))}     | {_mfmt(alt_m.get('sortino'))}      | {_mfmt(bh_m.get('sortino'))}")
                print(f"[PHASE3]   Max Drawdown       | {_mfmt(prod_nf.get('max_drawdown'), '%')}    | {_mfmt(alt_m.get('max_drawdown'), '%')}     | {_mfmt(bh_m.get('max_drawdown'), '%')}")
                print(f"[PHASE3]   Calmar             | {_mfmt(prod_nf.get('calmar'))}     | {_mfmt(alt_m.get('calmar'))}      | {_mfmt(bh_m.get('calmar'))}")
                if alt_ra_m:
                    print("[PHASE3] ───────────────────────────────────────────────────────────────")
                    print("[PHASE3]   RULE A filtered variant:")
                    print(f"[PHASE3]   Total Return       | {_mfmt(prod_ra.get('total_return'), '%')}    | {_mfmt(alt_ra_m.get('total_return'), '%')}     |")
                    print(f"[PHASE3]   Annual Return      | {_mfmt(prod_ra.get('annualized_return'), '%')}    | {_mfmt(alt_ra_m.get('annualized_return'), '%')}     |")
                    print(f"[PHASE3]   Sharpe             | {_mfmt(prod_ra.get('sharpe'))}     | {_mfmt(alt_ra_m.get('sharpe'))}      |")
                    print(f"[PHASE3]   Sortino            | {_mfmt(prod_ra.get('sortino'))}     | {_mfmt(alt_ra_m.get('sortino'))}      |")
                    print(f"[PHASE3]   Max Drawdown       | {_mfmt(prod_ra.get('max_drawdown'), '%')}    | {_mfmt(alt_ra_m.get('max_drawdown'), '%')}     |")
                    print(f"[PHASE3]   Calmar             | {_mfmt(prod_ra.get('calmar'))}     | {_mfmt(alt_ra_m.get('calmar'))}      |")
                print("[PHASE3] ───────────────────────────────────────────────────────────────")
                print("[PHASE3] Interpretation: if Alternative's Sharpe ≥ Production's AND Max DD")
                print("[PHASE3]   stays well below SPY B&H's, Q5-only defensive is the better rule")
                print("[PHASE3]   for the current regime. Alternative sacrifices some Q5-crash")
                print("[PHASE3]   protection in exchange for capturing Q4 upside (65 months in")
                print("[PHASE3]   current data with +7% avg 6M SPY return).")
                print("[PHASE3] ═══════════════════════════════════════════════════════════════")
    except Exception as _alt_err:
        print(f"[PHASE3] Alt-allocation diagnostic failed: {_alt_err}")

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
            "rf_monthly": rf_monthly,
        },
    }


# ---------------------------------------------------------------------------
# 3A.2 — Extended backtest: crash detection + drawdowns + filter triggers
# ---------------------------------------------------------------------------

def run_phase3_backtest_with_drawdowns(phase2_result, gli_data, spy_daily,
                                        phase1_result=None):
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
    phase1_dataset = phase1_result.get("full_dataset", []) if phase1_result else []
    for rule_name in ["rule_a", "rule_b", "rule_c"]:
        fs = filtered_signals.get(rule_name, [])
        triggers = _build_filter_triggers(fs, spy_returns, phase1_dataset)
        n_correct = sum(1 for t in triggers if t.get("was_correct"))
        n_total = sum(1 for t in triggers if t.get("was_correct") is not None)
        accuracy = round(n_correct / n_total * 100, 1) if n_total > 0 else 0
        result[f"{rule_name}_filter_triggers"] = triggers
        print(f"[PHASE3] {rule_name}: {len(triggers)} triggers, "
              f"{n_correct}/{n_total} correct ({accuracy}%)")

    print("[PHASE3] 3A.2 complete.")

    # Store internals for 3A.3 extension
    result["_internals"] = internals
    return result


# ---------------------------------------------------------------------------
# 3.5 — Sensitivity grid + assessment
# ---------------------------------------------------------------------------

def _make_rule_a(x_thresh, y_thresh):
    """Rule A: Credit-Only filter (inline to avoid circular import)."""
    def rule(row):
        pctl = row.get("hy_oas_level_percentile")
        chg = row.get("hy_oas_3m_change")
        if pctl is None or chg is None or pd.isna(pctl) or pd.isna(chg):
            return False
        return pctl < x_thresh and chg < y_thresh
    return rule


def _compute_sensitivity_grid(phase1_dataset, original_quintiles, spy_returns,
                               alloc_map, pctl_thresholds=None, chg_thresholds=None,
                               rf_monthly=None):
    """Compute Sharpe/DD/precision across a threshold grid for Rule A.

    Args:
        phase1_dataset: list of dicts from Phase 1 full_dataset
        original_quintiles: pd.Series Q1-Q5 (DatetimeIndex)
        spy_returns: pd.Series of monthly SPY returns
        alloc_map: dict {quintile: weight}
        pctl_thresholds: list of percentile thresholds to test
        chg_thresholds: list of 3m change thresholds (bps) to test

    Returns:
        dict with grids (sharpe, max_dd, total_return, precision, signals_filtered,
              tp_retention, fp_reduction), top5, current_rank
    """
    if pctl_thresholds is None:
        pctl_thresholds = SENSITIVITY_PCTL
    if chg_thresholds is None:
        chg_thresholds = SENSITIVITY_CHG

    df = pd.DataFrame(phase1_dataset)
    # Add COVID flag
    df["is_covid_preserve"] = df["signal_date"].isin(COVID_PRESERVE_DATES)

    # Label lookup for precision calculation
    label_lookup = {}
    for _, row in df.iterrows():
        dt = row.get("signal_date")
        label = row.get("label_moderate_tp")
        if dt is not None and label is not None and not (isinstance(label, float) and np.isnan(label)):
            label_lookup[dt] = int(label)

    total_tp = sum(1 for v in label_lookup.values() if v == 1)
    total_fp = sum(1 for v in label_lookup.values() if v == 0)

    n_pctl = len(pctl_thresholds)
    n_chg = len(chg_thresholds)

    sharpe_grid = [[0.0] * n_chg for _ in range(n_pctl)]
    max_dd_grid = [[0.0] * n_chg for _ in range(n_pctl)]
    total_return_grid = [[0.0] * n_chg for _ in range(n_pctl)]
    precision_grid = [[0.0] * n_chg for _ in range(n_pctl)]
    signals_filtered_grid = [[0] * n_chg for _ in range(n_pctl)]
    tp_retention_grid = [[0.0] * n_chg for _ in range(n_pctl)]
    fp_reduction_grid = [[0.0] * n_chg for _ in range(n_pctl)]

    all_combos = []

    for pi, pctl in enumerate(pctl_thresholds):
        for ci, chg in enumerate(chg_thresholds):
            rule_fn = _make_rule_a(pctl, chg)

            # Find filter dates
            filter_dates = set()
            filtered_tp = 0
            filtered_fp = 0
            for _, row in df.iterrows():
                if row.get("is_covid_preserve"):
                    continue
                if rule_fn(row):
                    date_str = row["signal_date"]
                    filter_dates.add(date_str)
                    label = label_lookup.get(date_str)
                    if label == 1:
                        filtered_tp += 1
                    elif label == 0:
                        filtered_fp += 1

            n_filtered = len(filter_dates)
            precision = filtered_fp / n_filtered if n_filtered > 0 else 0
            tp_retained = 1.0 - (filtered_tp / total_tp if total_tp > 0 else 0)
            fp_reduced = filtered_fp / total_fp if total_fp > 0 else 0

            # Apply filter to quintiles and simulate
            variant_q = original_quintiles.copy()
            for dt in variant_q.index:
                if dt.strftime("%Y-%m-%d") in filter_dates:
                    variant_q[dt] = 3

            sim = _simulate_variant(variant_q, spy_returns, alloc_map, rf_monthly=rf_monthly)
            if sim:
                m = _compute_metrics(sim, rf_monthly=rf_monthly)
                sharpe_grid[pi][ci] = m["sharpe"]
                max_dd_grid[pi][ci] = m["max_drawdown"]
                total_return_grid[pi][ci] = m["total_return"]
            else:
                sharpe_grid[pi][ci] = 0
                max_dd_grid[pi][ci] = 0
                total_return_grid[pi][ci] = 0

            precision_grid[pi][ci] = round(precision * 100, 1)
            signals_filtered_grid[pi][ci] = n_filtered
            tp_retention_grid[pi][ci] = round(tp_retained * 100, 1)
            fp_reduction_grid[pi][ci] = round(fp_reduced * 100, 1)

            all_combos.append({
                "pctl": pctl,
                "chg_bps": chg,
                "sharpe": sharpe_grid[pi][ci],
                "total_return": total_return_grid[pi][ci],
                "max_drawdown": max_dd_grid[pi][ci],
                "precision": precision_grid[pi][ci],
                "signals_filtered": n_filtered,
                "tp_retention": tp_retention_grid[pi][ci],
                "fp_reduction": fp_reduction_grid[pi][ci],
            })

    # Sort by Sharpe for top-5
    all_combos.sort(key=lambda x: x["sharpe"], reverse=True)
    top5 = all_combos[:5]

    # Find rank of current production threshold (pctl=15, 3m=10)
    current_rank = next(
        (i + 1 for i, c in enumerate(all_combos)
         if c["pctl"] == 15 and c["chg_bps"] == 10),
        None,
    )

    return {
        "pctl_thresholds": pctl_thresholds,
        "change_thresholds": chg_thresholds,
        "sharpe_grid": sharpe_grid,
        "max_dd_grid": max_dd_grid,
        "total_return_grid": total_return_grid,
        "precision_grid": precision_grid,
        "signals_filtered_grid": signals_filtered_grid,
        "tp_retention_grid": tp_retention_grid,
        "fp_reduction_grid": fp_reduction_grid,
        "top5_combinations": top5,
        "current_rank": current_rank,
        "total_combinations": len(all_combos),
    }


def _assess_sensitivity(grid_result):
    """Assess sensitivity gradient and threshold position.

    Returns:
        dict with gradient_assessment, position_assessment, robustness_recommendation
    """
    sharpe_grid = grid_result["sharpe_grid"]
    pctl_thresholds = grid_result["pctl_thresholds"]
    chg_thresholds = grid_result["change_thresholds"]

    # Find current production threshold indices
    try:
        pi_curr = pctl_thresholds.index(15)
        ci_curr = chg_thresholds.index(10)
    except ValueError:
        return {
            "gradient_assessment": "UNKNOWN",
            "position_assessment": "UNKNOWN",
            "robustness_recommendation": "WIDEN search",
        }

    current_sharpe = sharpe_grid[pi_curr][ci_curr]

    # Compute gradient: max absolute Sharpe difference among neighbors
    neighbors = []
    for dpi in [-1, 0, 1]:
        for dci in [-1, 0, 1]:
            if dpi == 0 and dci == 0:
                continue
            ni = pi_curr + dpi
            nj = ci_curr + dci
            if 0 <= ni < len(pctl_thresholds) and 0 <= nj < len(chg_thresholds):
                neighbors.append(sharpe_grid[ni][nj])

    if not neighbors:
        max_neighbor_diff = 0
    else:
        max_neighbor_diff = max(abs(current_sharpe - n) for n in neighbors)

    if max_neighbor_diff < 0.05:
        gradient = "SMOOTH"
    elif max_neighbor_diff < 0.15:
        gradient = "MODERATE"
    else:
        gradient = "SHARP"

    # Position: is current threshold at the peak, center, or edge of optimal region?
    flat_sharpes = [sharpe_grid[i][j]
                    for i in range(len(pctl_thresholds))
                    for j in range(len(chg_thresholds))]
    max_sharpe = max(flat_sharpes)
    sharpe_range = max_sharpe - min(flat_sharpes)

    # "Near optimal" = within 90% of the range from min to max
    near_optimal_threshold = min(flat_sharpes) + 0.9 * sharpe_range if sharpe_range > 0 else max_sharpe

    # Count how many neighbors are also near-optimal
    n_near_optimal_neighbors = sum(1 for n in neighbors if n >= near_optimal_threshold)

    if current_sharpe >= max_sharpe - 0.01:
        # At or very near the peak
        if n_near_optimal_neighbors >= 3:
            position = "CENTER"
        else:
            position = "PEAK"
    elif current_sharpe >= near_optimal_threshold:
        if n_near_optimal_neighbors >= 2:
            position = "CENTER"
        else:
            position = "EDGE"
    else:
        position = "EDGE"

    # Recommendation
    if gradient in ("SMOOTH", "MODERATE") and position == "CENTER":
        recommendation = "CONFIRM"
    elif gradient == "SHARP" or position == "PEAK":
        # Find the center of the best region
        best_combo = grid_result["top5_combinations"][0] if grid_result["top5_combinations"] else None
        if best_combo and (best_combo["pctl"] != 15 or best_combo["chg_bps"] != 10):
            recommendation = f"SHIFT to (pctl<{best_combo['pctl']}, 3m<{best_combo['chg_bps']}bps)"
        else:
            recommendation = "CONFIRM"
    elif position == "EDGE":
        recommendation = "WIDEN search"
    else:
        recommendation = "CONFIRM"

    return {
        "gradient_assessment": gradient,
        "position_assessment": position,
        "robustness_recommendation": recommendation,
        "current_sharpe": current_sharpe,
        "max_neighbor_diff": round(max_neighbor_diff, 4),
        "max_grid_sharpe": round(max_sharpe, 4),
    }


# ---------------------------------------------------------------------------
# 3A.3 — Monte Carlo + recommendation
# ---------------------------------------------------------------------------

MC_N_PERMUTATIONS = 10000


def _monte_carlo_sharpe_test(quintiles, spy_returns, alloc_map, n_perms=MC_N_PERMUTATIONS,
                              rf_monthly=None):
    """Permutation test for signal timing value.

    Fixes the SPY return sequence and shuffles quintile assignments to build
    a null distribution of Sharpes achievable by random timing.

    Args:
        quintiles: pd.Series of Q1-Q5 assignments
        spy_returns: pd.Series of monthly SPY returns (aligned)
        alloc_map: dict {quintile: weight}
        n_perms: number of permutations
        rf_monthly: pd.Series of monthly risk-free rate (decimal). Applied to
            both the actual and permuted portfolios as the cash-leg return.

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
    rf_vals = _align_rf(aligned["ret"], rf_monthly).values

    # Actual Sharpe (arithmetic mean excess, cash leg earns rf)
    weights = np.array([alloc_map.get(int(q), 1.0) for q in q_vals])
    actual_port = ret_vals * weights + rf_vals * (1 - weights)
    actual_excess = actual_port - rf_vals
    actual_sd = float(actual_excess.std())
    actual_sharpe = round(float(actual_excess.mean()) / actual_sd * float(np.sqrt(12)), 3) if actual_sd > 1e-12 else 0.0

    # Permutation loop
    rng = np.random.default_rng(seed=42)
    perm_sharpes = np.zeros(n_perms)

    for i in range(n_perms):
        shuffled_q = rng.permutation(q_vals)
        w = np.array([alloc_map.get(int(q), 1.0) for q in shuffled_q])
        perm_ret = ret_vals * w + rf_vals * (1 - w)
        perm_excess = perm_ret - rf_vals
        sd = perm_excess.std()
        if sd > 1e-12 and len(perm_ret) >= 12:
            perm_sharpes[i] = perm_excess.mean() / sd * np.sqrt(12)
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
                             n_perms=MC_N_PERMUTATIONS, rf_monthly=None):
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
    rf_vals = _align_rf(aligned["ret"], rf_monthly).values

    # Identify where overrides happened and which indices are Q4/Q5
    override_mask = q_orig != q_filt
    n_overrides = int(override_mask.sum())
    q45_indices = np.where((q_orig == 4) | (q_orig == 5))[0]

    if n_overrides == 0 or len(q45_indices) == 0:
        return {"actual_delta": 0.0, "p_value": 1.0, "significant": False}

    def _port_sharpe(w):
        port = ret_vals * w + rf_vals * (1 - w)
        excess = port - rf_vals
        sd = excess.std()
        return float(excess.mean() / sd * np.sqrt(12)) if sd > 1e-12 else 0.0

    # Actual delta
    w_orig = np.array([alloc_map.get(int(q), 1.0) for q in q_orig])
    w_filt = np.array([alloc_map.get(int(q), 1.0) for q in q_filt])
    sharpe_orig = _port_sharpe(w_orig)
    sharpe_filt = _port_sharpe(w_filt)
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
        perm_deltas[i] = _port_sharpe(w_perm) - sharpe_orig

    p_value = float(np.mean(perm_deltas >= actual_delta))

    return {
        "actual_delta": round(actual_delta, 4),
        "p_value": round(p_value, 4),
        "significant": p_value < 0.05,
    }


def _build_recommendation(metrics, deltas, alpha_decomp, subperiod_sharpes,
                           filter_accuracy, mc_results, sensitivity_assessment,
                           phase2_winning):
    """Build recommendation with 7 criteria (Phase 3.5 updated).

    Criteria:
      1. Sharpe Improvement (delta > 0.10)
      2. Drawdown Preservation (max DD within 2pp of unfiltered)
      3. Alpha Significance (t-stat > 2.0)
      4. Subperiod Consistency (no period degrades > 0.10 Sharpe)
      5. Filter Precision (>70% of filtered signals were genuine FPs)
      6. Monte Carlo Significance (p < 0.01)
      7. Threshold Robustness (SMOOTH/MODERATE gradient, CENTER/near-CENTER)

    Returns:
        dict with recommended_rule, confidence, criteria list, reasoning
    """
    rule_keys = ["rule_a", "rule_b", "rule_c"]
    nf = metrics.get("no_filter", {})
    n_criteria = 7
    max_score = n_criteria * 2

    rule_scores = {}

    for rule in rule_keys:
        rm = metrics.get(rule, {})
        if not rm:
            continue

        criteria = []
        score = 0

        # 1. Sharpe Improvement (pass if delta > 0.10)
        delta_key = f"{rule}_vs_no_filter"
        d = deltas.get(delta_key, {})
        sharpe_d = d.get("sharpe", {}).get("value", 0)
        if sharpe_d > 0.10:
            criteria.append({
                "name": "Sharpe Improvement",
                "result": "pass",
                "detail": f"Sharpe {rm['sharpe']} vs No Filter {nf.get('sharpe', 0)} "
                          f"(\u0394={sharpe_d:+.2f} > 0.10)",
            })
            score += 2
        elif sharpe_d > 0.03:
            criteria.append({
                "name": "Sharpe Improvement",
                "result": "marginal",
                "detail": f"Sharpe {rm['sharpe']} vs No Filter {nf.get('sharpe', 0)} "
                          f"(\u0394={sharpe_d:+.2f}, below 0.10 threshold)",
            })
            score += 1
        else:
            criteria.append({
                "name": "Sharpe Improvement",
                "result": "fail",
                "detail": f"Sharpe {rm['sharpe']} vs No Filter {nf.get('sharpe', 0)} "
                          f"(\u0394={sharpe_d:+.2f})",
            })

        # 2. Drawdown Preservation (pass if max DD within 2pp of unfiltered)
        dd_d = d.get("max_drawdown", {}).get("value", 0)
        if abs(dd_d) <= 2.0:
            criteria.append({
                "name": "Drawdown Preservation",
                "result": "pass",
                "detail": f"Max DD {rm['max_drawdown']:.1f}% vs No Filter "
                          f"{nf.get('max_drawdown', 0):.1f}% (\u0394={dd_d:+.1f}pp, within 2pp)",
            })
            score += 2
        elif abs(dd_d) <= 5.0:
            criteria.append({
                "name": "Drawdown Preservation",
                "result": "marginal",
                "detail": f"Max DD delta {dd_d:+.1f}pp (outside 2pp but within 5pp)",
            })
            score += 1
        else:
            criteria.append({
                "name": "Drawdown Preservation",
                "result": "fail",
                "detail": f"Max DD degraded by {dd_d:+.1f}pp",
            })

        # 3. Alpha Significance (pass if t-stat > 2.0)
        alpha = alpha_decomp.get(rule, {})
        t_stat = alpha.get("t_stat", 0)
        alpha_pct = alpha.get("alpha_annual_pct", 0)
        if abs(t_stat) > 2.0:
            criteria.append({
                "name": "Alpha Significance",
                "result": "pass",
                "detail": f"CAPM alpha {alpha_pct:+.2f}% (t={t_stat:.2f}, significant)",
            })
            score += 2
        elif abs(t_stat) > 1.5:
            criteria.append({
                "name": "Alpha Significance",
                "result": "marginal",
                "detail": f"CAPM alpha {alpha_pct:+.2f}% (t={t_stat:.2f})",
            })
            score += 1
        else:
            criteria.append({
                "name": "Alpha Significance",
                "result": "fail",
                "detail": f"CAPM alpha {alpha_pct:+.2f}% (t={t_stat:.2f}, weak)",
            })

        # 4. Subperiod Consistency (pass if no period degrades > 0.10 Sharpe)
        max_degradation = 0
        n_periods = 0
        for period, sharpes in subperiod_sharpes.items():
            rule_s = sharpes.get(rule)
            nf_s = sharpes.get("no_filter")
            if rule_s is not None and nf_s is not None:
                n_periods += 1
                degradation = nf_s - rule_s
                if degradation > max_degradation:
                    max_degradation = degradation
        if n_periods > 0 and max_degradation <= 0.10:
            criteria.append({
                "name": "Subperiod Consistency",
                "result": "pass",
                "detail": f"No subperiod degrades > 0.10 Sharpe "
                          f"(worst: {max_degradation:+.3f})",
            })
            score += 2
        elif n_periods > 0 and max_degradation <= 0.20:
            criteria.append({
                "name": "Subperiod Consistency",
                "result": "marginal",
                "detail": f"Worst subperiod degradation: {max_degradation:.3f}",
            })
            score += 1
        else:
            criteria.append({
                "name": "Subperiod Consistency",
                "result": "fail",
                "detail": f"Subperiod degradation: {max_degradation:.3f} (> 0.10)",
            })

        # 5. Filter Precision (pass if > 70% of filtered were genuine FPs)
        acc = filter_accuracy.get(rule, {})
        precision_pct = acc.get("precision", 0) * 100
        tn = acc.get("true_negatives", 0)
        t2 = acc.get("type_ii_errors", 0)
        if precision_pct > 70:
            criteria.append({
                "name": "Filter Precision",
                "result": "pass",
                "detail": f"Precision {precision_pct:.0f}% "
                          f"({tn} correct filters, {t2} over-filtered TPs)",
            })
            score += 2
        elif precision_pct > 50:
            criteria.append({
                "name": "Filter Precision",
                "result": "marginal",
                "detail": f"Precision {precision_pct:.0f}% ({tn}/{tn + t2})",
            })
            score += 1
        else:
            criteria.append({
                "name": "Filter Precision",
                "result": "fail",
                "detail": f"Precision {precision_pct:.0f}% — too many TPs over-filtered",
            })

        # 6. Monte Carlo Significance (pass if p < 0.01)
        mc_delta = mc_results.get("delta_tests", {}).get(f"{rule}_vs_no_filter", {})
        mc_p = mc_delta.get("p_value", 1.0)
        if mc_p < 0.01:
            criteria.append({
                "name": "Monte Carlo Significance",
                "result": "pass",
                "detail": f"Sharpe improvement p={mc_p:.4f} (significant at 1%)",
            })
            score += 2
        elif mc_p < 0.05:
            criteria.append({
                "name": "Monte Carlo Significance",
                "result": "marginal",
                "detail": f"Sharpe improvement p={mc_p:.4f} (significant at 5% but not 1%)",
            })
            score += 1
        else:
            criteria.append({
                "name": "Monte Carlo Significance",
                "result": "fail",
                "detail": f"Sharpe improvement p={mc_p:.4f} (not significant)",
            })

        # 7. Threshold Robustness (pass if SMOOTH/MODERATE + CENTER)
        sa = sensitivity_assessment or {}
        gradient = sa.get("gradient_assessment", "UNKNOWN")
        position = sa.get("position_assessment", "UNKNOWN")
        if gradient in ("SMOOTH", "MODERATE") and position == "CENTER":
            criteria.append({
                "name": "Threshold Robustness",
                "result": "pass",
                "detail": f"Gradient: {gradient}, Position: {position} — robust threshold",
            })
            score += 2
        elif gradient in ("SMOOTH", "MODERATE"):
            criteria.append({
                "name": "Threshold Robustness",
                "result": "marginal",
                "detail": f"Gradient: {gradient}, Position: {position}",
            })
            score += 1
        else:
            criteria.append({
                "name": "Threshold Robustness",
                "result": "fail",
                "detail": f"Gradient: {gradient}, Position: {position} — potential overfitting",
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

    # Confidence: 7 criteria, HIGH=6-7 pass, MODERATE=4-5, LOW=2-3, REJECT=0-1
    n_pass = sum(1 for c in best_criteria if c["result"] == "pass")
    if n_pass >= 6:
        confidence = "high"
    elif n_pass >= 4:
        confidence = "moderate"
    elif n_pass >= 2:
        confidence = "low"
    else:
        confidence = "reject"

    if best_score < 4:
        best_rule = "no_filter"
        confidence = "reject"

    n_marginal = sum(1 for c in best_criteria if c["result"] == "marginal")
    n_fail = sum(1 for c in best_criteria if c["result"] == "fail")

    if best_rule == "no_filter":
        reasoning = (
            f"No filter rule meets minimum criteria. Best candidate scored "
            f"{best_score}/{max_score} ({n_pass} pass, {n_marginal} marginal, {n_fail} fail). "
            f"Recommend retaining the unfiltered production signal."
        )
    else:
        label = VARIANT_LABELS.get(best_rule, best_rule)
        p2_match = " (matches Phase 2 winner)" if best_rule == phase2_winning else ""
        reasoning = (
            f"{label}{p2_match} scores {best_score}/{max_score} across {n_criteria} criteria "
            f"({n_pass} pass, {n_marginal} marginal, {n_fail} fail). "
        )
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

def run_phase3_backtest(phase2_result, gli_data, spy_daily, phase1_result=None):
    """Run the complete Phase 3 + 3.5 backtest.

    Combines all layers:
      3A.1: equity_curves, metrics, deltas, subperiod_sharpes, alpha_decomp
      3A.2: crash_detection, drawdowns, rule filter triggers
      3A.3: monte_carlo, recommendation
      3.5:  filter_accuracy_reframed, sensitivity, updated recommendation

    Args:
        phase2_result: dict from run_phase2_analysis()
        gli_data: dict from build_gli_signal() with 'quintiles' pd.Series
        spy_daily: pd.Series of daily SPY close prices
        phase1_result: optional dict from run_diagnostic() with 'full_dataset'

    Returns:
        Full backtest result dict
    """
    # Run 3A.1 + 3A.2
    result = run_phase3_backtest_with_drawdowns(
        phase2_result, gli_data, spy_daily, phase1_result
    )
    if "error" in result:
        return result

    internals = result.pop("_internals", {})
    sims = internals.get("sims", {})
    spy_returns = internals.get("spy_returns", pd.Series(dtype=float))
    filtered_signals = internals.get("filtered_signals", {})
    rf_monthly = internals.get("rf_monthly")

    alloc_map = ALLOC_MAP
    phase1_dataset = phase1_result.get("full_dataset", []) if phase1_result else []

    # ── 13. Monte Carlo permutation tests ────────────────────────────────
    print(f"[PHASE3] Running Monte Carlo ({MC_N_PERMUTATIONS} permutations)...")
    mc_variants = {}
    for name, sim in sims.items():
        if sim:
            mc_variants[name] = _monte_carlo_sharpe_test(
                sim["quintiles"], spy_returns, alloc_map, rf_monthly=rf_monthly,
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
                    spy_returns, alloc_map, rf_monthly=rf_monthly,
                )

    result["monte_carlo"] = {
        "n_permutations": MC_N_PERMUTATIONS,
        "variants": mc_variants,
        "delta_tests": mc_delta_tests,
    }
    print("[PHASE3] Monte Carlo complete.")

    # ── 14. Reframed filter accuracy (Phase 3.5) ────────────────────────
    filter_accuracy = {}
    if phase1_dataset:
        print("[PHASE3.5] Computing reframed filter accuracy...")
        for rule_name in ["rule_a", "rule_b", "rule_c"]:
            fs = filtered_signals.get(rule_name, [])
            fa = _compute_filter_accuracy_reframed(fs, phase1_dataset)
            filter_accuracy[rule_name] = fa
            print(f"[PHASE3.5] {rule_name}: precision={fa['precision']:.1%}, "
                  f"recall={fa['recall']:.1%}, F1={fa['f1']:.3f}")
    result["filter_accuracy_reframed"] = filter_accuracy

    # ── 15. Sensitivity grid (Phase 3.5) ─────────────────────────────────
    sensitivity_assessment = {}
    if phase1_dataset:
        print("[PHASE3.5] Computing sensitivity grid (7x7 = 49 backtests)...")
        original_quintiles = gli_data["quintiles"]
        # Re-align to common range
        common_idx = original_quintiles.index.intersection(spy_returns.index)
        oq_aligned = original_quintiles.reindex(common_idx)
        sr_aligned = spy_returns.reindex(common_idx)

        grid_result = _compute_sensitivity_grid(
            phase1_dataset, oq_aligned, sr_aligned, alloc_map, rf_monthly=rf_monthly,
        )
        sensitivity_assessment = _assess_sensitivity(grid_result)
        result["sensitivity"] = {**grid_result, **sensitivity_assessment}
        print(f"[PHASE3.5] Sensitivity: gradient={sensitivity_assessment['gradient_assessment']}, "
              f"position={sensitivity_assessment['position_assessment']}, "
              f"recommendation={sensitivity_assessment['robustness_recommendation']}")
    else:
        result["sensitivity"] = None

    # ── 16b. FF5 + Momentum multi-factor alpha ───────────────────────────
    print("[PHASE3] Computing FF5 + Momentum alpha...")
    ff5_mom_alpha = {}
    for name, sim in sims.items():
        if sim is None:
            continue
        try:
            res = compute_ff5_mom_alpha(sim["returns"])
            if "error" in res:
                print(f"[PHASE3] FF5+Mom {name}: {res['error']}")
            else:
                capm_a = res["comparison"]["capm_alpha"]
                ff5_a = res["comparison"]["ff5_mom_alpha"]
                absorbed = res["comparison"]["alpha_absorbed_pct"]
                print(f"[PHASE3] FF5+Mom {name}: CAPM={capm_a}% FF5={ff5_a}% absorbed={absorbed}%")
            ff5_mom_alpha[name] = res
        except Exception as e:
            print(f"[PHASE3] FF5+Mom {name} exception: {e}")
            ff5_mom_alpha[name] = {"error": str(e)}
    result["ff5_mom_alpha"] = ff5_mom_alpha

    # ── 17. Recommendation (Phase 3.5 updated — 7 criteria) ─────────────
    print("[PHASE3] Building recommendation...")
    result["recommendation"] = _build_recommendation(
        metrics=result["metrics"],
        deltas=result["deltas"],
        alpha_decomp=result["alpha_decomp"],
        subperiod_sharpes=result["subperiod_sharpes"],
        filter_accuracy=filter_accuracy,
        mc_results=result["monte_carlo"],
        sensitivity_assessment=sensitivity_assessment,
        phase2_winning=phase2_result.get("winning_rule", "rule_a"),
    )

    print(f"[PHASE3] Recommendation: {result['recommendation']['recommended_rule']} "
          f"(confidence: {result['recommendation']['confidence']})")
    print("[PHASE3] Full Phase 3 + 3.5 backtest complete.")
    return result
