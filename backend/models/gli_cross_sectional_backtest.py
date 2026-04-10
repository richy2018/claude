"""GLI Cross-Sectional Backtest + Conditional Leverage (Phase 3+4).

Compares single-asset vs cross-sectional vs leveraged variants.
Includes CAPM alpha decomposition.
"""

import numpy as np
import pandas as pd

from .backtest_engine import sortino_ratio


def _metrics(ret, label=""):
    """Compute portfolio metrics from monthly returns."""
    if len(ret) < 12:
        return {"label": label, "error": "insufficient data"}
    eq = (1 + ret).cumprod()
    years = len(ret) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(ret.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    sort = sortino_ratio(ret)
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0
    total = round(float(eq.iloc[-1] - 1) * 100, 1)
    turnover = round(float(ret.diff().abs().mean()) * 100, 2)
    return {
        "label": label, "sharpe": sharpe, "sortino": sort, "max_dd": max_dd,
        "calmar": calmar, "total_return": total, "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2), "turnover": turnover,
    }


def _capm_alpha(strategy_ret, benchmark_ret):
    """CAPM regression: strategy = α + β × benchmark + ε."""
    common = strategy_ret.index.intersection(benchmark_ret.index)
    if len(common) < 24:
        return None
    y = strategy_ret.reindex(common).values
    x = benchmark_ret.reindex(common).values
    X = np.column_stack([np.ones(len(x)), x])
    try:
        betas = np.linalg.lstsq(X, y, rcond=None)[0]
        alpha_monthly = float(betas[0])
        beta = float(betas[1])
        resid = y - X @ betas
        r_sq = 1 - np.var(resid) / max(np.var(y), 1e-10)
        alpha_annual = alpha_monthly * 12 * 100  # Annualized %
        se = float(np.std(resid) / np.sqrt(len(resid)))
        t_stat = alpha_monthly / se if se > 1e-10 else 0
        return {
            "alpha_annual_pct": round(alpha_annual, 2),
            "beta": round(beta, 3),
            "r_squared": round(float(r_sq), 3),
            "t_stat": round(t_stat, 2),
            "significant": abs(t_stat) > 2,
        }
    except Exception:
        return None


def apply_conditional_leverage(strategy_returns, ff_monthly, signal_quintiles,
                                max_leverage=2.0, ff_threshold=2.0):
    """Apply conditional leverage based on Fed Funds rate.

    Rules:
    - FF < 1%: up to max_leverage
    - FF 1-3%: up to 1.5x
    - FF > 3%: no leverage (1x)
    - Never lever during Q5 (bearish)
    """
    common = strategy_returns.index
    ff_aligned = ff_monthly.reindex(common, method="ffill").fillna(3)
    q_aligned = signal_quintiles.reindex(common, method="ffill").fillna(3)

    leverage = pd.Series(1.0, index=common)
    for i in range(len(common)):
        ff = float(ff_aligned.iloc[i])
        q = int(q_aligned.iloc[i]) if pd.notna(q_aligned.iloc[i]) else 3

        if q >= 5:  # Never lever during Q5
            leverage.iloc[i] = 1.0
        elif ff < 1.0:
            leverage.iloc[i] = max_leverage
        elif ff < ff_threshold:
            leverage.iloc[i] = min(1.5, max_leverage)
        else:
            leverage.iloc[i] = 1.0

    # Levered return = leverage × strategy_return - (leverage - 1) × monthly_ff_rate
    ff_monthly_rate = ff_aligned / 100 / 12  # Monthly financing cost
    lev_ret = leverage * strategy_returns - (leverage - 1) * ff_monthly_rate

    return lev_ret, leverage


def run_cross_sectional_backtest(xsect_results, ratio_series, spy_monthly, fred_data=None):
    """Run full backtest comparison across all variants + leverage.

    xsect_results: output from run_cross_sectional (Phase 1+2)
    """
    from .backtest_engine import (
        _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
        ALLOCATION_RULES, _signal_momentum,
    )

    if not xsect_results or "error" in xsect_results:
        return {"error": "Run cross-sectional analysis first"}

    portfolio = xsect_results.get("portfolio")
    if not portfolio or "chart" not in portfolio:
        return {"error": "No portfolio data from cross-sectional analysis"}

    # Reconstruct returns from chart data
    chart = portfolio["chart"]
    dates = pd.DatetimeIndex([c["date"] for c in chart])

    lo_eq = pd.Series([c["long_only"] for c in chart], index=dates)
    ls_eq = pd.Series([c["long_short"] for c in chart], index=dates)
    bh_eq = pd.Series([c["spy_bh"] for c in chart], index=dates)

    lo_ret = lo_eq.pct_change().dropna()
    ls_ret = ls_eq.pct_change().dropna()
    bh_ret = bh_eq.pct_change().dropna()

    # Build signal quintiles for leverage decision
    _PROD = PRODUCTION_MODELS["5f"]
    components = _extract_components(ratio_series)
    base_idx = components[_PROD["keys"][0]].index
    for k in _PROD["keys"][1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _PROD["keys"]:
        if k in components:
            comp += _PROD["weights"][k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    signal = _signal_momentum(comp, 1).dropna()

    quintiles = pd.Series(3, index=signal.index, dtype=int)
    for i in range(20, len(signal)):
        hist = signal.iloc[:i+1]
        pct = float((hist <= hist.iloc[-1]).mean()) * 100
        quintiles.iloc[i] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5

    # Get Fed Funds
    ff_monthly = None
    if fred_data is not None and isinstance(fred_data, pd.DataFrame):
        for col in ["FEDFUNDS", "DFF"]:
            if col in fred_data.columns:
                ff_monthly = fred_data[col].dropna().resample("MS").last()
                break

    # Compute all variants
    variants = [
        _metrics(bh_ret, "SPY Buy & Hold"),
        _metrics(lo_ret, "Cross-Sect Long-Only"),
        _metrics(ls_ret, "Cross-Sect Long/Short"),
    ]

    # Equal-weight rotation (top 5 pro-regime)
    # Already computed in lo_ret — use as proxy

    # Leverage variants
    lev_chart = {}
    if ff_monthly is not None:
        for lev_name, max_lev, ff_thresh in [
            ("Conservative (1.5x, FF<1%)", 1.5, 1.0),
            ("Moderate (2x, FF<2%)", 2.0, 2.0),
            ("Aggressive (2x, FF<3%)", 2.0, 3.0),
        ]:
            lev_ret, lev_ratio = apply_conditional_leverage(
                lo_ret, ff_monthly, quintiles, max_leverage=max_lev, ff_threshold=ff_thresh)
            m = _metrics(lev_ret, f"Levered {lev_name}")
            m["avg_leverage"] = round(float(lev_ratio.mean()), 2)
            m["pct_leveraged"] = round(float((lev_ratio > 1.0).mean()) * 100, 1)
            variants.append(m)

            # Store equity curve
            lev_eq = (1 + lev_ret).cumprod()
            lev_chart[lev_name] = lev_eq

    # CAPM alpha for each non-benchmark variant
    for v in variants[1:]:  # Skip B&H
        if v["label"].startswith("Cross-Sect Long-Only"):
            alpha = _capm_alpha(lo_ret, bh_ret)
        elif v["label"].startswith("Cross-Sect Long/Short"):
            alpha = _capm_alpha(ls_ret, bh_ret)
        elif "Levered" in v["label"] and ff_monthly is not None:
            # Find the corresponding levered return
            for ln, ml, ft in [("Conservative", 1.5, 1.0), ("Moderate", 2.0, 2.0), ("Aggressive", 2.0, 3.0)]:
                if ln in v["label"]:
                    lr, _ = apply_conditional_leverage(lo_ret, ff_monthly, quintiles, ml, ft)
                    alpha = _capm_alpha(lr, bh_ret)
                    break
            else:
                alpha = None
        else:
            alpha = None
        v["capm_alpha"] = alpha

    # Equity curves for chart
    eq_chart = []
    for d in lo_ret.index:
        entry = {
            "date": d.strftime("%Y-%m-%d"),
            "long_only": round(float(lo_eq.get(d, 1)), 4),
            "long_short": round(float(ls_eq.get(d, 1)), 4),
            "spy_bh": round(float(bh_eq.get(d, 1)), 4),
        }
        for ln, leq in lev_chart.items():
            if d in leq.index:
                entry[f"lev_{ln[:4]}"] = round(float(leq[d]), 4)
        eq_chart.append(entry)

    return {
        "variants": variants,
        "chart": eq_chart,
        "n_months": len(lo_ret),
        "has_leverage": ff_monthly is not None,
    }
