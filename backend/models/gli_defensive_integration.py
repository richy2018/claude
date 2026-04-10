"""Phase 3+4 — GLI Defensive Rotation Integration & Regime-Conditional Selection.

Combines defensive portfolio with GLI signal. Tests 4 modes:
1. Cash default (baseline)
2. Fixed defensive portfolio
3. Graduated (Q4=50% def, Q5=100% def)
4. Signal-proportional (scales with signal magnitude)

Phase 4: Regime-conditional defensive (rate hiking/cutting/inflation).
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES,
)

_3FA = PRODUCTION_MODELS["3fa_eq"]
_3FA_KEYS = _3FA["keys"]
_3FA_WEIGHTS = _3FA["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]
_ALLOC = ALLOCATION_RULES["production"]


def _build_signal_and_quintiles(ratio_series):
    """Build production signal and quintile assignments."""
    components = _extract_components(ratio_series)
    missing = [k for k in _3FA_KEYS if k not in components]
    if missing:
        return None, None, f"Missing: {missing}"

    base_idx = components[_3FA_KEYS[0]].index
    for k in _3FA_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _3FA_KEYS:
        if k in components:
            comp += _3FA_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    signal = _SIG_FN(comp).dropna()

    try:
        quintiles = pd.qcut(signal, 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return signal, None, "Cannot form quintiles"

    return signal, quintiles, None


def _portfolio_metrics(port_ret, label=""):
    """Compute portfolio metrics from monthly returns."""
    if len(port_ret) < 12:
        return {"error": "Not enough data"}

    eq = (1 + port_ret).cumprod()
    years = len(port_ret) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port_ret.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0
    total_ret = round(float(eq.iloc[-1] - 1) * 100, 1)

    return {
        "name": label,
        "total_return": total_ret,
        "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
    }


def _build_defensive_returns(defensive_weights, monthly_returns_dict, index):
    """Build weighted defensive portfolio returns on given index."""
    port = pd.Series(0.0, index=index)
    total_w = 0
    for ticker, weight in defensive_weights.items():
        if ticker in monthly_returns_dict:
            r = monthly_returns_dict[ticker].reindex(index).fillna(0)
            port += weight * r
            total_w += weight
    if total_w > 0 and abs(total_w - 1.0) > 0.01:
        port = port / total_w  # Renormalize
    return port


def simulate_rotation_modes(ratio_series, spy_monthly, defensive_weights,
                             defensive_returns_dict, vix_data=None):
    """Simulate 4 rotation modes and compare.

    Each month: equity_weight from quintile mapping, remaining goes to defensive.
    """
    signal, quintiles, err = _build_signal_and_quintiles(ratio_series)
    if err:
        return {"error": err}

    spy_ret = spy_monthly.pct_change().dropna()

    # Align everything
    common = signal.index.intersection(spy_ret.index).intersection(quintiles.index)
    for t in defensive_returns_dict:
        common = common.intersection(defensive_returns_dict[t].index)
    common = sorted(common)
    if len(common) < 36:
        return {"error": "Not enough common dates"}

    idx = pd.DatetimeIndex(common)
    q = quintiles.reindex(idx)
    sr = spy_ret.reindex(idx)
    eq_weight = q.map(_ALLOC).astype(float)  # Equity allocation per quintile

    # Vol scaling (same as production)
    vol_scalar = pd.Series(1.0, index=idx)
    if vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        vix_aligned = vix_m.reindex(idx, method="ffill").clip(lower=0.05)
        vol_scalar = (0.10 / vix_aligned).clip(upper=2.0)

    eq_weight_vs = (eq_weight * vol_scalar).clip(upper=1.0)
    def_weight = 1.0 - eq_weight_vs  # Freed allocation

    def_ret = _build_defensive_returns(defensive_weights, defensive_returns_dict, idx)

    results = {}
    bh_ret = sr  # Buy and hold SPX
    bh_metrics = _portfolio_metrics(bh_ret, "Buy & Hold")

    # Mode 1: Cash default (freed allocation earns 0)
    mode1_ret = eq_weight_vs * sr
    results["cash"] = _portfolio_metrics(mode1_ret, "Cash Default")

    # Mode 2: Fixed defensive (freed allocation → 100% defensive portfolio)
    mode2_ret = eq_weight_vs * sr + def_weight * def_ret
    results["fixed_defensive"] = _portfolio_metrics(mode2_ret, "Fixed Defensive")

    # Mode 3: Graduated (Q4 → 50% def + 50% cash, Q5 → 100% def)
    grad_def_frac = pd.Series(0.0, index=idx)
    grad_def_frac[q == 4] = 0.5
    grad_def_frac[q == 5] = 1.0
    # Q1-Q3: no freed allocation, but if vol-scaled below 1.0, the freed part is split
    grad_def_frac[q <= 3] = 0.5  # Even non-defensive months get partial defensive
    mode3_ret = eq_weight_vs * sr + def_weight * grad_def_frac * def_ret
    results["graduated"] = _portfolio_metrics(mode3_ret, "Graduated (50/100%)")

    # Mode 4: Signal-proportional (defensive weight scales with signal magnitude)
    sig_pct = signal.reindex(idx).rank(pct=True)
    # When signal is more negative (lower percentile), more defensive
    def_intensity = (1 - sig_pct).clip(0, 1)
    mode4_ret = eq_weight_vs * sr + def_weight * def_intensity * def_ret
    results["proportional"] = _portfolio_metrics(mode4_ret, "Signal-Proportional")

    # Equity curves for chart
    chart = []
    cash_eq = (1 + mode1_ret).cumprod()
    fixed_eq = (1 + mode2_ret).cumprod()
    bh_eq = (1 + bh_ret).cumprod()
    for d in idx:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "cash": round(float(cash_eq[d]), 4),
            "defensive": round(float(fixed_eq[d]), 4),
            "buyhold": round(float(bh_eq[d]), 4),
        })

    # Return gap analysis
    bh_total = bh_metrics.get("total_return", 0)
    for mode_name, mode_result in results.items():
        gap = bh_total - mode_result.get("total_return", 0)
        mode_result["return_gap_vs_bh"] = round(gap, 1)

    cash_gap = bh_total - results["cash"].get("total_return", 0)
    fixed_gap = bh_total - results["fixed_defensive"].get("total_return", 0)
    gap_closed = round(cash_gap - fixed_gap, 1) if cash_gap > 0 else 0
    gap_closed_pct = round(gap_closed / cash_gap * 100, 1) if cash_gap > 0 else 0

    return {
        "modes": results,
        "buyhold": bh_metrics,
        "chart": chart,
        "gap_analysis": {
            "bh_total_return": bh_total,
            "cash_total_return": results["cash"].get("total_return", 0),
            "defensive_total_return": results["fixed_defensive"].get("total_return", 0),
            "return_gap_cash": round(cash_gap, 1),
            "return_gap_defensive": round(fixed_gap, 1),
            "gap_closed": gap_closed,
            "gap_closed_pct": gap_closed_pct,
        },
        "n_months": len(idx),
        "defensive_weights": defensive_weights,
    }


def regime_conditional_defensive(ratio_series, spy_monthly, defensive_returns_dict,
                                  fred_data, vix_data=None, n_perms=5000):
    """Phase 4: Condition defensive allocation on rate regime.

    Rate hiking: overweight SHY + GLD, underweight TLT
    Rate cutting: overweight TLT + IEF
    Inflation spike: overweight TIP + GLD + DBC
    Default: equal weight across top assets
    """
    signal, quintiles, err = _build_signal_and_quintiles(ratio_series)
    if err:
        return {"error": err}

    if fred_data is None or not isinstance(fred_data, pd.DataFrame):
        return {"error": "No FRED data for regime classification"}

    # Rate regime from Fed Funds
    ff = None
    for col in ["FEDFUNDS", "DFF"]:
        if col in fred_data.columns:
            ff = fred_data[col].dropna().resample("MS").last()
            break

    if ff is None or len(ff) < 12:
        return {"error": "No Fed Funds data"}

    ff_chg = ff.diff(6)

    # CPI for inflation detection
    cpi = fred_data.get("CPIAUCSL") if "CPIAUCSL" in fred_data.columns else None
    cpi_yoy = None
    if cpi is not None:
        cpi_m = cpi.dropna().resample("MS").last()
        cpi_yoy = cpi_m.pct_change(12) * 100

    # Define regime portfolios (using available tickers)
    available = set(defensive_returns_dict.keys())
    regime_portfolios = {}

    # Rate hiking: short duration + gold
    hiking_tickers = [t for t in ["SHY", "GLD", "TIP", "BIL"] if t in available]
    if hiking_tickers:
        regime_portfolios["hiking"] = {t: 1.0 / len(hiking_tickers) for t in hiking_tickers}

    # Rate cutting: long duration
    cutting_tickers = [t for t in ["TLT", "IEF", "AGG", "LQD"] if t in available]
    if cutting_tickers:
        regime_portfolios["cutting"] = {t: 1.0 / len(cutting_tickers) for t in cutting_tickers}

    # Inflation: real assets
    inflation_tickers = [t for t in ["TIP", "GLD", "DBC", "VNQ"] if t in available]
    if inflation_tickers:
        regime_portfolios["inflation"] = {t: 1.0 / len(inflation_tickers) for t in inflation_tickers}

    # Default: equal weight across all available
    default_tickers = list(available - {"SH", "HYG"})[:6]
    if default_tickers:
        regime_portfolios["default"] = {t: 1.0 / len(default_tickers) for t in default_tickers}

    if not regime_portfolios.get("default"):
        return {"error": "No default defensive portfolio possible"}

    spy_ret = spy_monthly.pct_change().dropna()
    common = signal.index.intersection(spy_ret.index)
    for t in defensive_returns_dict:
        common = common.intersection(defensive_returns_dict[t].index)
    common = common.intersection(ff_chg.dropna().index)
    common = sorted(common)
    idx = pd.DatetimeIndex(common)

    if len(idx) < 36:
        return {"error": "Not enough common dates for regime analysis"}

    q = quintiles.reindex(idx)
    sr = spy_ret.reindex(idx)
    eq_weight = q.map(_ALLOC).astype(float)

    # Vol scaling
    vol_scalar = pd.Series(1.0, index=idx)
    if vix_data is not None:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        vix_aligned = vix_m.reindex(idx, method="ffill").clip(lower=0.05)
        vol_scalar = (0.10 / vix_aligned).clip(upper=2.0)
    eq_weight_vs = (eq_weight * vol_scalar).clip(upper=1.0)
    def_weight = 1.0 - eq_weight_vs

    # Classify each month's regime
    ff_aligned = ff_chg.reindex(idx, method="ffill")
    regime_labels = pd.Series("default", index=idx)
    if cpi_yoy is not None:
        cpi_aligned = cpi_yoy.reindex(idx, method="ffill")
        regime_labels[cpi_aligned > 4] = "inflation"
    regime_labels[(ff_aligned > 0) & (regime_labels == "default")] = "hiking"
    regime_labels[(ff_aligned < 0) & (regime_labels == "default")] = "cutting"

    # Build regime-conditional defensive returns
    regime_def_ret = pd.Series(0.0, index=idx)
    for d in idx:
        reg = regime_labels[d]
        port = regime_portfolios.get(reg, regime_portfolios["default"])
        r = 0.0
        tw = 0.0
        for t, w in port.items():
            if t in defensive_returns_dict:
                val = defensive_returns_dict[t].get(d, 0)
                if pd.notna(val):
                    r += w * val
                    tw += w
        regime_def_ret[d] = r / tw if tw > 0 else 0

    # Static defensive returns (default portfolio)
    static_def_ret = _build_defensive_returns(
        regime_portfolios["default"], defensive_returns_dict, idx)

    # Mode comparison: regime-conditional vs static
    rc_port = eq_weight_vs * sr + def_weight * regime_def_ret
    static_port = eq_weight_vs * sr + def_weight * static_def_ret
    cash_port = eq_weight_vs * sr

    rc_metrics = _portfolio_metrics(rc_port, "Regime-Conditional")
    static_metrics = _portfolio_metrics(static_port, "Static Defensive")
    cash_metrics = _portfolio_metrics(cash_port, "Cash Default")

    # Monte Carlo: shuffle regime labels
    print(f"[DEF REGIME MC] Running {n_perms} permutations...")
    real_sharpe = rc_metrics["sharpe"]
    regime_vals = regime_labels.values.copy()

    null_sharpes = np.empty(n_perms)
    for i in range(n_perms):
        shuffled = np.random.permutation(regime_vals)
        shuf_def_ret = pd.Series(0.0, index=idx)
        for j, d in enumerate(idx):
            reg = shuffled[j]
            port = regime_portfolios.get(reg, regime_portfolios["default"])
            r = 0.0
            tw = 0.0
            for t, w in port.items():
                if t in defensive_returns_dict:
                    val = defensive_returns_dict[t].get(d, 0)
                    if pd.notna(val):
                        r += w * val
                        tw += w
            shuf_def_ret.iloc[j] = r / tw if tw > 0 else 0

        shuf_port = eq_weight_vs * sr + def_weight * shuf_def_ret
        if len(shuf_port) < 12:
            null_sharpes[i] = 0
            continue
        eq_s = (1 + shuf_port).cumprod()
        years = len(shuf_port) / 12
        ar = float(eq_s.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq_s.iloc[-1] > 0 else 0
        av = float(shuf_port.std() * np.sqrt(12))
        null_sharpes[i] = round(ar / av, 3) if av > 1e-8 else 0

        if (i + 1) % 1000 == 0:
            print(f"[DEF REGIME MC] {i+1}/{n_perms}")

    p_value = float(np.mean(null_sharpes >= real_sharpe))
    print(f"[DEF REGIME MC] Real={real_sharpe:.3f}, null_mean={np.mean(null_sharpes):.3f}, p={p_value:.4f}")

    # Regime distribution
    regime_counts = {r: int((regime_labels == r).sum()) for r in ["hiking", "cutting", "inflation", "default"]}

    return {
        "regime_conditional": rc_metrics,
        "static_defensive": static_metrics,
        "cash_default": cash_metrics,
        "improvement_vs_static": round(rc_metrics["sharpe"] - static_metrics["sharpe"], 3),
        "monte_carlo": {
            "real_sharpe": real_sharpe,
            "p_value": round(p_value, 4),
            "null_mean": round(float(np.mean(null_sharpes)), 3),
            "n_permutations": n_perms,
        },
        "significant": p_value < 0.10,
        "regime_portfolios": regime_portfolios,
        "regime_distribution": regime_counts,
        "current_regime": str(regime_labels.iloc[-1]) if len(regime_labels) > 0 else "unknown",
    }


def run_defensive_study(ratio_series, spy_monthly, fred_data=None, vix_data=None):
    """Full defensive rotation study: screening → portfolio → integration → regime.

    Orchestrator that runs all phases and returns combined results.
    """
    import yfinance as yf

    print("[DEFENSIVE] === Phase 1: Asset Screening ===")
    from .gli_defensive_assets import run_asset_screening, build_optimal_defensive_portfolio
    screening = run_asset_screening(ratio_series, spy_monthly)
    if "error" in screening:
        return {"error": f"Screening failed: {screening['error']}"}

    print(f"\n[DEFENSIVE] === Phase 2: Optimal Portfolio ===")
    portfolio = build_optimal_defensive_portfolio(screening, spy_monthly, ratio_series)

    # Download returns for all screened tickers
    print(f"\n[DEFENSIVE] === Phase 3: Integration Backtest ===")
    tickers = [a["ticker"] for a in screening.get("assets", [])]
    defensive_returns = {}
    for ticker in tickers:
        try:
            data = yf.download(ticker, start="2003-01-01", progress=False)
            close = data["Close"]
            if hasattr(close, "droplevel") and close.index.nlevels > 1:
                close = close.droplevel(1)
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            defensive_returns[ticker] = close.resample("MS").last().dropna().pct_change().dropna()
        except Exception:
            pass

    # Use optimized weights if available, else equal weight top 6
    def_weights = portfolio.get("optimized_weights", {})
    if not def_weights:
        top6 = [a["ticker"] for a in screening["assets"][:6] if a["ticker"] not in ("SH", "HYG")]
        def_weights = {t: 1.0 / len(top6) for t in top6}

    integration = simulate_rotation_modes(
        ratio_series, spy_monthly, def_weights, defensive_returns, vix_data)

    print(f"\n[DEFENSIVE] === Phase 4: Regime-Conditional ===")
    regime = None
    if fred_data is not None:
        regime = regime_conditional_defensive(
            ratio_series, spy_monthly, defensive_returns, fred_data, vix_data, n_perms=5000)

    # Summary
    gap = integration.get("gap_analysis", {})
    print(f"\n[DEFENSIVE] === SUMMARY ===")
    print(f"  Cash strategy total return: {gap.get('cash_total_return')}%")
    print(f"  Defensive strategy total return: {gap.get('defensive_total_return')}%")
    print(f"  Buy & Hold total return: {gap.get('bh_total_return')}%")
    print(f"  Gap closed: {gap.get('gap_closed')}% ({gap.get('gap_closed_pct')}%)")

    return {
        "screening": screening,
        "portfolio": portfolio,
        "integration": integration,
        "regime": regime,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("GLI Defensive Rotation Study")
    print("=" * 60)
    print("Call run_defensive_study(ratio_series, spy_monthly, fred_data, vix_data)")
