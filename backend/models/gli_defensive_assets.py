"""Phase 1+2 — GLI Defensive Asset Screening & Portfolio Construction.

Screens 17 defensive alternatives for performance during GLI Q4/Q5 months.
Builds optimal defensive portfolio from top assets.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]
_ALLOC = ALLOCATION_RULES["production"]

DEFENSIVE_TICKERS = {
    # Fixed Income
    "TLT": "20+ Year Treasury",
    "IEF": "7-10 Year Treasury",
    "SHY": "1-3 Year Treasury",
    "TIP": "TIPS (Inflation-Protected)",
    "AGG": "US Aggregate Bond",
    "LQD": "Investment Grade Corporate",
    "HYG": "High Yield Corporate",
    # Defensive Equity Sectors
    "XLU": "Utilities",
    "XLP": "Consumer Staples",
    "XLV": "Health Care",
    "XLRE": "Real Estate",
    # Alternatives
    "GLD": "Gold",
    "DBC": "Broad Commodities",
    "VNQ": "REITs",
    # Cash baseline
    "BIL": "T-Bill (Cash Proxy)",
    # Inverse (Q5 only)
    "SH": "Short S&P 500 (1x)",
}

# Major crisis quarters for crisis alpha measurement
CRISIS_PERIODS = [
    ("2008-10-01", "2008-12-31", "GFC Q4-2008"),
    ("2020-02-01", "2020-03-31", "COVID Q1-2020"),
    ("2022-01-01", "2022-06-30", "Rate Shock H1-2022"),
    ("2018-10-01", "2018-12-31", "Vol Shock Q4-2018"),
]


def _build_prod_signal(components):
    """Build production 3FA_EQ Mom6M signal."""
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    return _SIG_FN(comp).dropna()


def _get_defensive_months(signal):
    """Return boolean mask of months in Q4 or Q5 (defensive)."""
    try:
        quintiles = pd.qcut(signal, 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return pd.Series(False, index=signal.index)
    return quintiles >= 4


def screen_single_asset(ticker, asset_returns, spy_returns, defensive_mask):
    """Screen a single defensive asset during GLI defensive months.

    Returns dict of defensive-period metrics.
    """
    # Align all series
    common = asset_returns.index.intersection(spy_returns.index).intersection(defensive_mask.index)
    if len(common) < 24:
        return None

    ar = asset_returns.reindex(common)
    sr = spy_returns.reindex(common)
    dm = defensive_mask.reindex(common)

    n_defensive = int(dm.sum())
    if n_defensive < 12:
        return None

    # Defensive-period only metrics
    def_ret = ar[dm]
    def_spy = sr[dm]

    ann_ret = float(np.prod(1 + def_ret) ** (12.0 / len(def_ret)) - 1) if len(def_ret) > 0 else 0
    ann_vol = float(def_ret.std() * np.sqrt(12)) if len(def_ret) > 1 else 0
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0

    # Max drawdown during defensive months
    eq = (1 + def_ret).cumprod()
    peak = eq.expanding().max()
    max_dd = float(((eq - peak) / peak).min()) if len(eq) > 0 else 0

    # Correlation with SPX during defensive periods
    spx_corr = float(def_ret.corr(def_spy)) if len(def_ret) > 10 else 0

    # Crisis alpha: average monthly return during worst SPX quarters
    crisis_returns = []
    for start, end, label in CRISIS_PERIODS:
        crisis_mask = (ar.index >= start) & (ar.index <= end)
        crisis_ret = ar[crisis_mask]
        if len(crisis_ret) > 0:
            crisis_returns.append(float(crisis_ret.mean()))

    crisis_alpha = float(np.mean(crisis_returns)) if crisis_returns else 0

    return {
        "ticker": ticker,
        "name": DEFENSIVE_TICKERS.get(ticker, ticker),
        "n_defensive_months": n_defensive,
        "n_total_months": len(common),
        "ann_return_defensive": round(ann_ret * 100, 2),
        "ann_vol_defensive": round(ann_vol * 100, 2),
        "sharpe_defensive": sharpe,
        "max_dd_defensive": round(max_dd * 100, 1),
        "spx_correlation": round(spx_corr, 3),
        "crisis_alpha": round(crisis_alpha * 100, 3),
        "n_crisis_periods": len(crisis_returns),
    }


def compute_defensive_score(results):
    """Rank assets by composite defensive score.

    Score = 0.4 × crisis_alpha_rank + 0.3 × defensive_sharpe_rank + 0.3 × (1 - |SPX_corr|)
    Higher = better.
    """
    if len(results) < 2:
        return results

    # Rank crisis alpha (higher = better → higher rank)
    ca_vals = [r["crisis_alpha"] for r in results]
    ca_sorted = sorted(range(len(ca_vals)), key=lambda i: ca_vals[i], reverse=True)
    ca_rank = [0] * len(results)
    for rank, idx in enumerate(ca_sorted):
        ca_rank[idx] = (len(results) - rank) / len(results)

    # Rank Sharpe (higher = better)
    sh_vals = [r["sharpe_defensive"] for r in results]
    sh_sorted = sorted(range(len(sh_vals)), key=lambda i: sh_vals[i], reverse=True)
    sh_rank = [0] * len(results)
    for rank, idx in enumerate(sh_sorted):
        sh_rank[idx] = (len(results) - rank) / len(results)

    # Low SPX correlation score (lower |corr| = better)
    for i, r in enumerate(results):
        corr_score = 1 - abs(r["spx_correlation"])
        score = 0.4 * ca_rank[i] + 0.3 * sh_rank[i] + 0.3 * corr_score
        r["defensive_score"] = round(score, 3)

    results.sort(key=lambda x: x["defensive_score"], reverse=True)
    return results


def run_asset_screening(ratio_series, spy_monthly):
    """Phase 1: Screen all defensive assets during GLI Q4/Q5 months.

    Downloads each ticker from Yahoo Finance, screens during defensive periods.
    """
    import yfinance as yf

    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return {"error": f"Missing components: {missing}"}

    signal = _build_prod_signal(components)
    defensive_mask = _get_defensive_months(signal)
    spy_ret = spy_monthly.pct_change().dropna()

    print(f"[DEFENSIVE] Signal: {len(signal)} pts, {int(defensive_mask.sum())} defensive months ({defensive_mask.mean()*100:.0f}%)")

    results = []
    failed = []

    for ticker in DEFENSIVE_TICKERS:
        try:
            data = yf.download(ticker, start="2003-01-01", progress=False)
            if data.empty or len(data) < 60:
                failed.append(f"{ticker}: insufficient data")
                continue

            close = data["Close"]
            if hasattr(close, "droplevel") and close.index.nlevels > 1:
                close = close.droplevel(1)
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]

            monthly = close.resample("MS").last().dropna()
            asset_ret = monthly.pct_change().dropna()

            result = screen_single_asset(ticker, asset_ret, spy_ret, defensive_mask)
            if result:
                results.append(result)
                print(f"[DEFENSIVE] {ticker}: Sharpe={result['sharpe_defensive']}, CrisisAlpha={result['crisis_alpha']}%, SPX_corr={result['spx_correlation']}")
            else:
                failed.append(f"{ticker}: not enough aligned data")
        except Exception as e:
            failed.append(f"{ticker}: {str(e)[:50]}")
            print(f"[DEFENSIVE] {ticker} failed: {e}")

    # Score and rank
    results = compute_defensive_score(results)

    # Find BIL baseline
    bil = next((r for r in results if r["ticker"] == "BIL"), None)

    return {
        "assets": results,
        "failed": failed,
        "n_screened": len(results),
        "n_defensive_months": int(defensive_mask.sum()),
        "pct_defensive": round(float(defensive_mask.mean()) * 100, 1),
        "cash_baseline": bil,
    }


def build_optimal_defensive_portfolio(asset_screening_results, spy_monthly,
                                       ratio_series, max_weight=0.40, min_weight=0.05,
                                       top_n=6):
    """Phase 2: Build optimal defensive portfolio from top screened assets.

    Mean-variance optimize: minimize SPX correlation subject to positive expected return.
    """
    import yfinance as yf

    assets = asset_screening_results.get("assets", [])
    if len(assets) < 3:
        return {"error": "Not enough screened assets"}

    # Filter to top_n by defensive score, exclude SH and HYG
    candidates = [a for a in assets if a["ticker"] not in ("SH", "HYG")][:top_n]
    tickers = [a["ticker"] for a in candidates]

    if len(tickers) < 3:
        return {"error": "Not enough candidate assets"}

    # Download all tickers
    components = _extract_components(ratio_series)
    signal = _build_prod_signal(components)
    defensive_mask = _get_defensive_months(signal)
    spy_ret = spy_monthly.pct_change().dropna()

    monthly_returns = {}
    for ticker in tickers:
        try:
            data = yf.download(ticker, start="2003-01-01", progress=False)
            close = data["Close"]
            if hasattr(close, "droplevel") and close.index.nlevels > 1:
                close = close.droplevel(1)
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            monthly = close.resample("MS").last().dropna()
            monthly_returns[ticker] = monthly.pct_change().dropna()
        except Exception as e:
            print(f"[DEFENSIVE OPT] Failed to download {ticker}: {e}")

    valid_tickers = [t for t in tickers if t in monthly_returns]
    if len(valid_tickers) < 3:
        return {"error": "Not enough valid ticker data"}

    # Build return matrix for defensive months only
    common = defensive_mask.index
    for t in valid_tickers:
        common = common.intersection(monthly_returns[t].index)
    common = common.intersection(spy_ret.index)
    common = sorted(common)

    dm = defensive_mask.reindex(common).fillna(False)
    def_dates = dm[dm].index

    if len(def_dates) < 20:
        return {"error": "Not enough defensive months for optimization"}

    ret_matrix = pd.DataFrame({t: monthly_returns[t].reindex(def_dates) for t in valid_tickers}).dropna()
    spy_def = spy_ret.reindex(ret_matrix.index)
    n = len(valid_tickers)

    # Objective: minimize portfolio correlation with SPX
    def _obj(weights):
        port_ret = ret_matrix.values @ weights
        corr = np.corrcoef(port_ret, spy_def.values)[0, 1]
        return corr  # Minimize correlation with SPX

    bounds = [(min_weight, max_weight)] * n
    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},
        # Positive expected return
        {'type': 'ineq', 'fun': lambda w: ret_matrix.values @ w @ np.ones(len(ret_matrix)) / len(ret_matrix)},
    ]

    # Multiple starting points
    starts = [
        np.ones(n) / n,  # Equal weight
        np.array([max_weight if i == 0 else min_weight for i in range(n)]),  # Concentrated in top
    ]
    # Add a start concentrating on assets with lowest SPX correlation
    corrs = [float(ret_matrix[t].corr(spy_def)) for t in valid_tickers]
    low_corr_w = np.array([1.0 / (abs(c) + 0.1) for c in corrs])
    low_corr_w = low_corr_w / low_corr_w.sum()
    starts.append(np.clip(low_corr_w, min_weight, max_weight))

    best_obj = 999
    best_w = np.ones(n) / n
    for x0 in starts:
        x0 = np.clip(x0, min_weight, max_weight)
        x0 = x0 / x0.sum()
        try:
            res = minimize(_obj, x0, method='SLSQP', bounds=bounds,
                           constraints=[{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}],
                           options={'maxiter': 500})
            if res.fun < best_obj:
                best_obj = res.fun
                best_w = res.x
        except Exception:
            continue

    # Compute optimized portfolio stats
    opt_port = ret_matrix.values @ best_w
    ann_ret = float(np.prod(1 + opt_port) ** (12.0 / len(opt_port)) - 1)
    ann_vol = float(np.std(opt_port) * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    eq_cum = np.cumprod(1 + opt_port)
    max_dd = round(float(np.min(eq_cum / np.maximum.accumulate(eq_cum) - 1)) * 100, 1)
    spx_corr = round(float(np.corrcoef(opt_port, spy_def.values)[0, 1]), 3)

    # Equal weight comparison
    eq_w = np.ones(n) / n
    eq_port = ret_matrix.values @ eq_w
    eq_ann = float(np.prod(1 + eq_port) ** (12.0 / len(eq_port)) - 1)
    eq_vol = float(np.std(eq_port) * np.sqrt(12))
    eq_sharpe = round(eq_ann / eq_vol, 3) if eq_vol > 1e-8 else 0

    weights_dict = {valid_tickers[i]: round(float(best_w[i]), 3) for i in range(n)}

    print(f"[DEFENSIVE OPT] Optimized: Sharpe={sharpe}, SPX_corr={spx_corr}, weights={weights_dict}")
    print(f"[DEFENSIVE OPT] Equal weight: Sharpe={eq_sharpe}")

    return {
        "tickers": valid_tickers,
        "optimized_weights": weights_dict,
        "equal_weights": {t: round(1.0 / n, 3) for t in valid_tickers},
        "n_defensive_months": len(def_dates),
        "optimized": {
            "ann_return": round(ann_ret * 100, 2),
            "ann_vol": round(ann_vol * 100, 2),
            "sharpe": sharpe,
            "max_dd": max_dd,
            "spx_correlation": spx_corr,
        },
        "equal_weight": {
            "ann_return": round(eq_ann * 100, 2),
            "ann_vol": round(eq_vol * 100, 2),
            "sharpe": eq_sharpe,
        },
    }


if __name__ == "__main__":
    print("=" * 60)
    print("GLI Defensive Asset Screening & Portfolio Construction")
    print("=" * 60)
    print("Call run_asset_screening(ratio_series, spy_monthly)")
    print("Then build_optimal_defensive_portfolio(screening_results, spy_monthly, ratio_series)")
