"""GLI Comprehensive Validation Stack — 10 Institutional-Grade Statistical Tests.

Tests: Deflated Sharpe, Binomial, Wilcoxon, Ljung-Box, Runs, R² equity,
Tail Ratio, OOS/IS ratio, PnL concentration, Alpha decomposition.
"""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES, sortino_ratio, _signal_momentum,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_FN = SIGNAL_TRANSFORMS[_PROD["signal_type"]][1]
_ALLOC = ALLOCATION_RULES["production"]


# ─── Test 1: Deflated Sharpe Ratio ──────────────────────────────────────────

def deflated_sharpe_ratio(returns, n_trials=150):
    """Correct observed Sharpe for multiple testing bias."""
    n = len(returns)
    if n < 24:
        return {"error": "insufficient data"}
    sr = float(returns.mean() / returns.std() * np.sqrt(12))
    skew = float(sp_stats.skew(returns))
    kurt = float(sp_stats.kurtosis(returns))  # excess kurtosis

    # Expected max SR from N random trials (Euler-Mascheroni approximation)
    gamma = 0.5772156649
    e_max_sr = np.sqrt(2 * np.log(n_trials)) - (np.log(np.pi) + gamma) / (2 * np.sqrt(2 * np.log(n_trials)))

    # SE of SR adjusted for non-normality (Lo 2002)
    se_sr = np.sqrt((1 + 0.5 * sr**2 - skew * sr + (kurt / 4) * sr**2) / n)

    # DSR test statistic
    dsr_stat = (sr - e_max_sr) / max(se_sr, 1e-10)
    p_value = 1 - sp_stats.norm.cdf(dsr_stat)

    return {
        "name": "Deflated Sharpe Ratio",
        "observed_sr": round(sr, 3),
        "e_max_sr": round(e_max_sr, 3),
        "n_trials": n_trials,
        "dsr_stat": round(dsr_stat, 3),
        "p_value": round(p_value, 6),
        "pass": p_value < 0.05,
    }


# ─── Test 2: Binomial Test ──────────────────────────────────────────────────

def binomial_test(returns):
    """Test whether positive months exceed chance (50%)."""
    n = len(returns)
    k = int((returns > 0).sum())
    try:
        p_val = sp_stats.binomtest(k, n, 0.5, alternative='greater').pvalue
    except AttributeError:
        p_val = sp_stats.binom_test(k, n, 0.5, alternative='greater')

    # Sub-period analysis
    sub_periods = [
        ("2003-2008", "2003-01-01", "2008-12-31"),
        ("2009-2014", "2009-01-01", "2014-12-31"),
        ("2015-2019", "2015-01-01", "2019-12-31"),
        ("2020-2025", "2020-01-01", "2025-12-31"),
    ]
    subs = []
    for label, s, e in sub_periods:
        mask = (returns.index >= s) & (returns.index <= e)
        sub = returns[mask]
        if len(sub) > 6:
            sk = int((sub > 0).sum())
            sn = len(sub)
            subs.append({"period": label, "positive": sk, "total": sn,
                          "pct": round(sk / sn * 100, 1)})

    return {
        "name": "Binomial Test (pos months > 50%)",
        "positive_months": k, "total_months": n,
        "pct_positive": round(k / n * 100, 1),
        "p_value": round(float(p_val), 6),
        "pass": float(p_val) < 0.05,
        "sub_periods": subs,
    }


# ─── Test 3: Wilcoxon Signed-Rank ───────────────────────────────────────────

def wilcoxon_test(returns):
    """Non-parametric test that median return > 0."""
    try:
        stat, p_val = sp_stats.wilcoxon(returns.dropna(), alternative='greater')
    except Exception:
        return {"name": "Wilcoxon Signed-Rank", "error": "test failed"}
    return {
        "name": "Wilcoxon Signed-Rank (median > 0)",
        "statistic": round(float(stat), 1),
        "p_value": round(float(p_val), 6),
        "median_monthly": round(float(returns.median()) * 100, 3),
        "pass": float(p_val) < 0.05,
    }


# ─── Test 4: Ljung-Box Autocorrelation ──────────────────────────────────────

def ljung_box_test(returns, lags=5):
    """Test for serial autocorrelation. PASS = no autocorrelation (p > 0.05)."""
    n = len(returns)
    r = returns.dropna().values

    # Lag-1 autocorrelation
    acf1 = float(np.corrcoef(r[:-1], r[1:])[0, 1])

    # Ljung-Box Q statistic (manual — no statsmodels dependency)
    acf_vals = []
    for k in range(1, lags + 1):
        if k < n:
            acf_vals.append(float(np.corrcoef(r[:-k], r[k:])[0, 1]))
    q_stat = n * (n + 2) * sum(a**2 / (n - k) for k, a in enumerate(acf_vals, 1))
    p_value = 1 - sp_stats.chi2.cdf(q_stat, lags)

    return {
        "name": f"Ljung-Box (lag {lags})",
        "q_statistic": round(q_stat, 2),
        "p_value": round(p_value, 4),
        "acf_lag1": round(acf1, 4),
        "pass": p_value > 0.05,  # PASS = no autocorrelation
        "note": "p>0.05 = no autocorrelation (good)" if p_value > 0.05 else "p<0.05 = autocorrelation detected (warning)",
    }


# ─── Test 5: Runs Test ──────────────────────────────────────────────────────

def runs_test(returns):
    """Test randomness of positive/negative return sequence."""
    signs = (returns > 0).astype(int).values
    n = len(signs)
    n1 = int(signs.sum())
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return {"name": "Runs Test", "error": "all same sign"}

    # Count runs
    runs = 1 + int(np.sum(np.diff(signs) != 0))
    expected = 1 + 2 * n0 * n1 / n
    var = 2 * n0 * n1 * (2 * n0 * n1 - n) / (n**2 * (n - 1))
    z = (runs - expected) / np.sqrt(max(var, 1e-10))
    p_value = 2 * (1 - sp_stats.norm.cdf(abs(z)))

    return {
        "name": "Runs Test (randomness)",
        "n_runs": runs, "expected_runs": round(expected, 1),
        "z_statistic": round(z, 3),
        "p_value": round(p_value, 4),
        "pass": p_value > 0.05,  # PASS = random sequence
    }


# ─── Test 6: R² of Equity Curve ─────────────────────────────────────────────

def equity_curve_r_squared(returns):
    """Measure smoothness of equity curve via R² of linear fit."""
    eq = (1 + returns).cumprod()
    x = np.arange(len(eq))

    # Linear R²
    slope, intercept, r_val, _, _ = sp_stats.linregress(x, eq.values)
    r_sq = r_val**2

    # Log R²
    log_eq = np.log(eq.clip(lower=1e-10).values)
    _, _, r_val_log, _, _ = sp_stats.linregress(x, log_eq)
    r_sq_log = r_val_log**2

    grade = "excellent" if r_sq > 0.95 else "good" if r_sq > 0.90 else "inconsistent"
    return {
        "name": "Equity Curve R²",
        "r_squared": round(r_sq, 4),
        "r_squared_log": round(r_sq_log, 4),
        "grade": grade,
        "pass": r_sq > 0.90,
    }


# ─── Test 7: Tail Ratio ─────────────────────────────────────────────────────

def tail_ratio(returns):
    """Compare right tail (wins) to left tail (losses)."""
    p95 = float(np.percentile(returns, 95))
    p5 = float(np.percentile(returns, 5))
    ratio = abs(p95 / p5) if abs(p5) > 1e-10 else 0
    skew = float(sp_stats.skew(returns))
    kurt = float(sp_stats.kurtosis(returns))

    return {
        "name": "Tail Ratio (95th/|5th|)",
        "tail_ratio": round(ratio, 3),
        "p95": round(p95 * 100, 2),
        "p5": round(p5 * 100, 2),
        "skewness": round(skew, 3),
        "excess_kurtosis": round(kurt, 3),
        "pass": ratio > 1.0,
    }


# ─── Test 8: OOS/IS Ratio ───────────────────────────────────────────────────

def oos_is_ratio(returns):
    """Compare IS vs OOS Sharpe at multiple split points."""
    n = len(returns)
    results = []
    for pct, label in [(50, "50/50"), (60, "60/40"), (70, "70/30")]:
        split = int(n * pct / 100)
        is_ret = returns.iloc[:split]
        oos_ret = returns.iloc[split:]
        if len(is_ret) < 12 or len(oos_ret) < 12:
            continue
        is_sr = float(is_ret.mean() / is_ret.std() * np.sqrt(12)) if is_ret.std() > 0 else 0
        oos_sr = float(oos_ret.mean() / oos_ret.std() * np.sqrt(12)) if oos_ret.std() > 0 else 0
        ratio = oos_sr / is_sr if abs(is_sr) > 0.01 else 0
        results.append({"split": label, "is_sharpe": round(is_sr, 3),
                         "oos_sharpe": round(oos_sr, 3), "ratio": round(ratio, 2)})

    avg_ratio = np.mean([r["ratio"] for r in results]) if results else 0
    grade = "robust" if avg_ratio > 0.8 else "some degradation" if avg_ratio > 0.5 else "likely overfit"
    return {
        "name": "OOS/IS Sharpe Ratio",
        "splits": results,
        "avg_ratio": round(avg_ratio, 2),
        "grade": grade,
        "pass": avg_ratio > 0.5,
    }


# ─── Test 9: PnL Concentration ──────────────────────────────────────────────

def pnl_concentration(returns):
    """Test whether returns are concentrated in few lucky months."""
    total_pnl = float(returns.sum())
    if abs(total_pnl) < 1e-10:
        return {"name": "PnL Concentration", "error": "zero total PnL"}

    sorted_ret = returns.sort_values(ascending=False)
    top5_pnl = float(sorted_ret.iloc[:5].sum())
    top10_pnl = float(sorted_ret.iloc[:10].sum())

    top5_pct = round(top5_pnl / total_pnl * 100, 1) if total_pnl > 0 else 0
    top10_pct = round(top10_pnl / total_pnl * 100, 1) if total_pnl > 0 else 0
    n_positive = int((returns > 0).sum())

    return {
        "name": "PnL Concentration",
        "top5_pct": top5_pct,
        "top10_pct": top10_pct,
        "n_positive": n_positive,
        "total_months": len(returns),
        "pass": top5_pct < 30,
        "note": "well-distributed" if top5_pct < 30 else "concentrated (fragile)" if top5_pct > 50 else "moderate",
    }


# ─── Test 10: Alpha Decomposition ───────────────────────────────────────────

def alpha_decomposition(strategy_returns, spy_returns, ff_monthly=None):
    """Decompose alpha into timing, allocation, and cash yield components."""
    common = strategy_returns.index.intersection(spy_returns.index)
    strat = strategy_returns.reindex(common)
    spy = spy_returns.reindex(common)

    total_alpha_monthly = float(strat.mean() - spy.mean())
    total_alpha_annual = round(total_alpha_monthly * 12 * 100, 2)

    # Timing alpha: difference between strategy and proportional buy-hold
    # Proportional = average allocation × market return
    avg_alloc = float((strat / spy.replace(0, np.nan)).dropna().clip(-2, 2).mean())
    proportional_ret = spy * avg_alloc
    timing_monthly = float(strat.mean() - proportional_ret.mean())
    timing_annual = round(timing_monthly * 12 * 100, 2)

    # Cash yield alpha
    cash_annual = 0.0
    if ff_monthly is not None and len(ff_monthly) > 0:
        ff_aligned = ff_monthly.reindex(common, method="ffill").fillna(0) / 100 / 12
        cash_contribution = float(ff_aligned.mean()) * (1 - avg_alloc)
        cash_annual = round(cash_contribution * 12 * 100, 2)

    # Allocation alpha = total - timing - cash
    allocation_annual = round(total_alpha_annual - timing_annual - cash_annual, 2)

    return {
        "name": "Alpha Decomposition",
        "total_alpha_annual": total_alpha_annual,
        "timing_alpha": timing_annual,
        "allocation_alpha": allocation_annual,
        "cash_yield_alpha": cash_annual,
        "avg_equity_allocation": round(avg_alloc * 100, 1),
    }


# ─── Orchestrator ────────────────────────────────────────────────────────────

def run_validation_stack(ratio_series, spy_monthly, vix_data=None, fred_data=None):
    """Run all 10 institutional-grade statistical tests."""
    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return {"error": f"Missing: {missing}"}

    # Build signal and run backtest
    base_idx = next(iter(components.values())).index
    comp = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    signal = _SIG_FN(comp).dropna()

    spy_ret = spy_monthly.pct_change().dropna()
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 60:
        return {"error": "Not enough aligned data"}

    # Compute quintiles and strategy returns
    try:
        quintiles = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return {"error": "Cannot form quintiles"}

    weights = quintiles.map(_ALLOC).astype(float)
    strat_ret = aligned["ret"] * weights

    print(f"[VALIDATION STACK] {len(strat_ret)} months of strategy returns")

    # Get Fed Funds for alpha decomposition
    ff_monthly = None
    if fred_data is not None and isinstance(fred_data, pd.DataFrame):
        for col in ["FEDFUNDS", "DFF"]:
            if col in fred_data.columns:
                ff_monthly = fred_data[col].dropna().resample("MS").last()
                break

    # Run all 10 tests
    tests = [
        deflated_sharpe_ratio(strat_ret),
        binomial_test(strat_ret),
        wilcoxon_test(strat_ret),
        ljung_box_test(strat_ret),
        runs_test(strat_ret),
        equity_curve_r_squared(strat_ret),
        tail_ratio(strat_ret),
        oos_is_ratio(strat_ret),
        pnl_concentration(strat_ret),
        alpha_decomposition(strat_ret, aligned["ret"], ff_monthly),
    ]

    n_pass = sum(1 for t in tests if t.get("pass", False))
    n_tests = sum(1 for t in tests if "pass" in t)

    # Sub-period Sharpes
    sub_sharpes = []
    for label, s, e in [("2003-2008", "2003", "2008"), ("2009-2014", "2009", "2014"),
                         ("2015-2019", "2015", "2019"), ("2020-2025", "2020", "2025")]:
        sub = strat_ret[(strat_ret.index.year >= int(s)) & (strat_ret.index.year <= int(e))]
        if len(sub) > 12:
            sr = float(sub.mean() / sub.std() * np.sqrt(12)) if sub.std() > 0 else 0
            sub_sharpes.append({"period": label, "sharpe": round(sr, 3), "n_months": len(sub)})

    # Performance summary
    eq = (1 + strat_ret).cumprod()
    years = len(strat_ret) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(strat_ret.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    sort = sortino_ratio(strat_ret)
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0

    # Print formatted summary
    print("\n" + "=" * 64)
    print("GLI 5F PRODUCTION MODEL — VALIDATION STACK")
    print("=" * 64)
    for t in tests:
        status = "✓ PASS" if t.get("pass") else "✗ FAIL" if "pass" in t else "  INFO"
        p = f"p={t['p_value']:.4f}" if "p_value" in t else ""
        print(f"  {status}  {t['name']:40s} {p}")
    print(f"\n  Score: {n_pass}/{n_tests} tests passed")
    print(f"  Sharpe: {sharpe}  Sortino: {sort}  MaxDD: {max_dd}%  Calmar: {calmar}")
    print("=" * 64)

    return {
        "tests": tests,
        "n_pass": n_pass,
        "n_tests": n_tests,
        "sub_period_sharpes": sub_sharpes,
        "performance": {
            "sharpe": sharpe, "sortino": sort, "max_dd": max_dd,
            "calmar": calmar, "ann_return": round(ann_ret * 100, 2),
            "total_return": round(float(eq.iloc[-1] - 1) * 100, 1),
        },
    }
