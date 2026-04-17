"""GLI Cross-Sectional Multi-Asset Strategy — Phase 1+2.

Phase 1: Estimate liquidity beta for each asset in the universe.
Phase 2: Build cross-sectional portfolio based on GLI regime.
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES, sortino_ratio, _signal_momentum, sharpe_ratio,
    _old_sharpe_geometric, rf_from_fred,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]

ASSET_UNIVERSE = {
    # Regional equities
    "SPY": {"name": "S&P 500", "class": "equity_region"},
    "QQQ": {"name": "Nasdaq 100", "class": "equity_region"},
    "EFA": {"name": "MSCI EAFE", "class": "equity_region"},
    "EEM": {"name": "MSCI EM", "class": "equity_region"},
    "FXI": {"name": "China Large Cap", "class": "equity_region"},
    # US sectors
    "XLK": {"name": "Technology", "class": "equity_sector"},
    "XLF": {"name": "Financials", "class": "equity_sector"},
    "XLE": {"name": "Energy", "class": "equity_sector"},
    "XLI": {"name": "Industrials", "class": "equity_sector"},
    "XLY": {"name": "Cons Discretionary", "class": "equity_sector"},
    "XLP": {"name": "Cons Staples", "class": "equity_sector"},
    "XLU": {"name": "Utilities", "class": "equity_sector"},
    "XLV": {"name": "Health Care", "class": "equity_sector"},
    "XLRE": {"name": "Real Estate", "class": "equity_sector"},
    # Fixed income
    "TLT": {"name": "20+ Yr Treasury", "class": "fixed_income"},
    "IEF": {"name": "7-10 Yr Treasury", "class": "fixed_income"},
    "SHY": {"name": "1-3 Yr Treasury", "class": "fixed_income"},
    "LQD": {"name": "IG Corporate", "class": "fixed_income"},
    "HYG": {"name": "HY Corporate", "class": "fixed_income"},
    "TIP": {"name": "TIPS", "class": "fixed_income"},
    # Alternatives
    "GLD": {"name": "Gold", "class": "alternative"},
    "DBC": {"name": "Commodities", "class": "alternative"},
    "USO": {"name": "Crude Oil", "class": "alternative"},
    "UUP": {"name": "US Dollar", "class": "alternative"},
}


def _build_gli_signal(ratio_series):
    """Build 5F composite signal (1M momentum)."""
    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return None, None, f"Missing: {missing}"
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    signal = _signal_momentum(comp, 1).dropna()  # 1M momentum
    return signal, comp, None


def download_asset_returns():
    """Download monthly adjusted-close returns for all assets."""
    import yfinance as yf
    returns = {}
    failed = []
    for ticker in ASSET_UNIVERSE:
        try:
            data = yf.download(ticker, start="2003-01-01", progress=False)
            if data.empty or len(data) < 60:
                failed.append(f"{ticker}: insufficient data")
                continue
            close = data.get("Adj Close", data["Close"])
            if hasattr(close, "droplevel") and close.index.nlevels > 1:
                close = close.droplevel(1)
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            monthly = close.resample("MS").last().dropna()
            ret = monthly.pct_change().dropna()
            if len(ret) > 36:
                returns[ticker] = ret
            else:
                failed.append(f"{ticker}: only {len(ret)} months")
        except Exception as e:
            failed.append(f"{ticker}: {str(e)[:40]}")
    print(f"[XSECT] Downloaded {len(returns)}/{len(ASSET_UNIVERSE)} assets, {len(failed)} failed")
    return returns, failed


def estimate_liquidity_betas(signal, asset_returns, spy_returns, window=60):
    """Estimate liquidity beta for each asset via rolling regression.

    asset_return_t = α + β_liq × ΔGLI_t-1 + β_mkt × SPX_return_t + ε
    """
    gli_change = signal.diff(1).dropna()  # Monthly change in GLI signal
    results = []

    for ticker, asset_ret in asset_returns.items():
        # Align all series
        common = gli_change.index.intersection(asset_ret.index).intersection(spy_returns.index)
        if len(common) < window + 12:
            continue

        y = asset_ret.reindex(common)
        x_gli = gli_change.shift(1).reindex(common)  # Lagged GLI change (no lookahead)
        x_mkt = spy_returns.reindex(common)

        # Drop NaN
        df = pd.DataFrame({"y": y, "gli": x_gli, "mkt": x_mkt}).dropna()
        if len(df) < window:
            continue

        # Full-sample regression
        X = np.column_stack([np.ones(len(df)), df["gli"].values, df["mkt"].values])
        try:
            betas = np.linalg.lstsq(X, df["y"].values, rcond=None)[0]
            beta_liq_full = float(betas[1])
        except Exception:
            continue

        # Rolling betas (for stability check)
        rolling_betas = []
        for i in range(window, len(df), 3):  # Step by 3 for speed
            chunk = df.iloc[i-window:i]
            Xr = np.column_stack([np.ones(len(chunk)), chunk["gli"].values, chunk["mkt"].values])
            try:
                br = np.linalg.lstsq(Xr, chunk["y"].values, rcond=None)[0]
                rolling_betas.append(float(br[1]))
            except Exception:
                continue

        # Stability: what fraction of rolling betas have the same sign as full-sample?
        if rolling_betas:
            same_sign = sum(1 for b in rolling_betas if np.sign(b) == np.sign(beta_liq_full))
            stability = round(same_sign / len(rolling_betas), 2)
        else:
            stability = 0

        # Classification
        if abs(beta_liq_full) < 0.5:
            classification = "neutral"
        elif beta_liq_full > 0:
            classification = "pro_liquidity"
        else:
            classification = "anti_liquidity"

        info = ASSET_UNIVERSE.get(ticker, {})
        results.append({
            "ticker": ticker,
            "name": info.get("name", ticker),
            "asset_class": info.get("class", "unknown"),
            "beta_liq": round(beta_liq_full, 3),
            "classification": classification,
            "stability": stability,
            "stable": stability >= 0.70,
            "n_months": len(df),
            "rolling_mean": round(float(np.mean(rolling_betas)), 3) if rolling_betas else None,
            "rolling_std": round(float(np.std(rolling_betas)), 3) if rolling_betas else None,
        })

    # Sort by liquidity beta descending
    results.sort(key=lambda x: x["beta_liq"], reverse=True)
    return results


# ─── Phase 2: Portfolio Construction ─────────────────────────────────────────

def build_regime_portfolios(signal, asset_returns, beta_table, ff_monthly=None):
    """Build cross-sectional portfolios based on GLI regime.

    Returns monthly portfolio returns for long-only and long/short variants.
    """
    # Expanding-window quintiles
    quintiles = pd.Series(3, index=signal.index, dtype=int)
    for i in range(20, len(signal)):
        hist = signal.iloc[:i+1]
        pct = float((hist <= hist.iloc[-1]).mean()) * 100
        quintiles.iloc[i] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5

    # Split assets by classification (only stable ones)
    pro = [a["ticker"] for a in beta_table if a["classification"] == "pro_liquidity" and a["stable"]]
    anti = [a["ticker"] for a in beta_table if a["classification"] == "anti_liquidity" and a["stable"]]
    neutral = [a["ticker"] for a in beta_table if a["classification"] == "neutral" and a["stable"]]
    all_tickers = list(set(pro + anti + neutral))

    if len(pro) < 2 or len(anti) < 2:
        # Fallback: use all available with beta sign
        pro = [a["ticker"] for a in beta_table if a["beta_liq"] > 0][:7]
        anti = [a["ticker"] for a in beta_table if a["beta_liq"] < 0][:7]

    # Find common dates
    common = signal.index
    for t in all_tickers:
        if t in asset_returns:
            common = common.intersection(asset_returns[t].index)
    common = sorted(common)
    if len(common) < 36:
        return None, None, "Not enough common dates"

    idx = pd.DatetimeIndex(common)

    # Cash rate
    cash_monthly = pd.Series(0.0, index=idx)
    if ff_monthly is not None:
        cash_monthly = ff_monthly.reindex(idx, method="ffill").fillna(0) / 100 / 12

    # Long-only portfolio
    port_lo = pd.Series(0.0, index=idx)
    # Long/short portfolio
    port_ls = pd.Series(0.0, index=idx)

    for i, d in enumerate(idx):
        q = quintiles.get(d, 3)

        if q <= 2:  # Bullish
            longs = pro[:5]
            shorts = anti[:3]
        elif q >= 4:  # Bearish
            longs = anti[:5]
            shorts = pro[:3]
        else:  # Neutral
            longs = (pro[:3] + anti[:3])[:5]
            shorts = []

        # Long-only: equal weight across longs, cash for rest
        n_long = len([t for t in longs if t in asset_returns])
        if n_long > 0:
            w_per = min(0.25, 1.0 / n_long)
            ret_lo = 0.0
            total_w = 0.0
            for t in longs:
                if t in asset_returns and d in asset_returns[t].index:
                    ret_lo += w_per * float(asset_returns[t][d])
                    total_w += w_per
            # Cash on remainder
            ret_lo += (1 - total_w) * float(cash_monthly.get(d, 0))
            port_lo.iloc[i] = ret_lo

        # Long/short: longs + shorts
        ret_ls = 0.0
        total_long_w = 0.0
        for t in longs:
            if t in asset_returns and d in asset_returns[t].index:
                w = min(0.25, 1.0 / max(len(longs), 1))
                ret_ls += w * float(asset_returns[t][d])
                total_long_w += w
        total_short_w = 0.0
        for t in shorts:
            if t in asset_returns and d in asset_returns[t].index:
                w = min(0.15, 0.30 / max(len(shorts), 1))
                ret_ls -= w * float(asset_returns[t][d])
                total_short_w += w
        # Cash on remainder (net of short proceeds)
        cash_frac = max(0, 1 - total_long_w)
        ret_ls += cash_frac * float(cash_monthly.get(d, 0))
        port_ls.iloc[i] = ret_ls

    return port_lo, port_ls, None


def run_cross_sectional(ratio_series, spy_monthly, fred_data=None):
    """Run Phase 1 (liquidity betas) + Phase 2 (portfolio construction)."""
    signal, comp, err = _build_gli_signal(ratio_series)
    if err:
        return {"error": err}

    print("[XSECT] Downloading asset universe...")
    asset_returns, failed = download_asset_returns()

    spy_ret = spy_monthly.pct_change().dropna()

    print("[XSECT] Estimating liquidity betas...")
    beta_table = estimate_liquidity_betas(signal, asset_returns, spy_ret)

    n_pro = sum(1 for b in beta_table if b["classification"] == "pro_liquidity")
    n_anti = sum(1 for b in beta_table if b["classification"] == "anti_liquidity")
    n_stable = sum(1 for b in beta_table if b["stable"])
    print(f"[XSECT] Betas: {len(beta_table)} assets, {n_pro} pro, {n_anti} anti, {n_stable} stable")

    # Get Fed Funds for cash yield
    ff_monthly = None
    if fred_data is not None and isinstance(fred_data, pd.DataFrame):
        for col in ["FEDFUNDS", "DFF"]:
            if col in fred_data.columns:
                ff_monthly = fred_data[col].dropna().resample("MS").last()
                break

    print("[XSECT] Building regime portfolios...")
    port_lo, port_ls, err2 = build_regime_portfolios(signal, asset_returns, beta_table, ff_monthly)

    portfolio_results = None
    if port_lo is not None:
        rf_monthly = rf_from_fred(fred_data, port_lo.index)

        def _metrics(ret, label):
            eq = (1 + ret).cumprod()
            years = len(ret) / 12
            ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
            ann_vol = float(ret.std() * np.sqrt(12))
            sharpe = sharpe_ratio(ret, rf=rf_monthly)
            sharpe_old = _old_sharpe_geometric(ret)
            sort = sortino_ratio(ret, rf=rf_monthly)
            peak = eq.expanding().max()
            max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
            total = round(float(eq.iloc[-1] - 1) * 100, 1)
            return {"label": label, "sharpe": sharpe, "sharpe_old_geometric": sharpe_old,
                    "sortino": sort, "max_dd": max_dd,
                    "total_return": total, "ann_return": round(ann_ret * 100, 2),
                    "ann_vol": round(ann_vol * 100, 2)}

        # SPY buy & hold on same dates
        spy_common = spy_ret.reindex(port_lo.index).fillna(0)
        bh_metrics = _metrics(spy_common, "SPY B&H")
        lo_metrics = _metrics(port_lo, "Cross-Sectional Long-Only")
        ls_metrics = _metrics(port_ls, "Cross-Sectional Long/Short")

        # Equity curves
        eq_lo = (1 + port_lo).cumprod()
        eq_ls = (1 + port_ls).cumprod()
        eq_bh = (1 + spy_common).cumprod()

        chart = []
        for d in port_lo.index:
            chart.append({
                "date": d.strftime("%Y-%m-%d"),
                "long_only": round(float(eq_lo[d]), 4),
                "long_short": round(float(eq_ls[d]), 4),
                "spy_bh": round(float(eq_bh[d]), 4),
            })

        portfolio_results = {
            "comparison": [bh_metrics, lo_metrics, ls_metrics],
            "chart": chart,
            "n_months": len(port_lo),
        }

        print(f"[XSECT] Long-only: Sharpe={lo_metrics['sharpe']}, Ret={lo_metrics['total_return']}%")
        print(f"[XSECT] Long/short: Sharpe={ls_metrics['sharpe']}, Ret={ls_metrics['total_return']}%")
        print(f"[XSECT] SPY B&H: Sharpe={bh_metrics['sharpe']}, Ret={bh_metrics['total_return']}%")

    # Current regime and allocation
    current_q = None
    if len(signal) > 20:
        hist = signal
        pct = float((hist <= hist.iloc[-1]).mean()) * 100
        current_q = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5

    return {
        "beta_table": beta_table,
        "failed_tickers": failed,
        "n_assets": len(beta_table),
        "n_pro": n_pro,
        "n_anti": n_anti,
        "n_stable": n_stable,
        "portfolio": portfolio_results,
        "current_regime": "bullish" if current_q and current_q <= 2 else "bearish" if current_q and current_q >= 4 else "neutral",
        "current_quintile": current_q,
    }
