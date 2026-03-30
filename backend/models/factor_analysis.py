"""Sector-level factor decomposition and attribution analysis."""

import pandas as pd
import numpy as np
from ..config import SECTOR_ETFS


SECTOR_ETF_MAP = {
    "Energy": "XLE",
    "Materials": "XLB",
    "Industrials": "XLI",
    "Consumer Disc": "XLY",
    "Consumer Staples": "XLP",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Info Tech": "XLK",
    "Comm Services": "XLC",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
}


def compute_factor_decomposition(
    stock_prices: pd.DataFrame,
    spy_prices: pd.Series,
    sector_etf_prices: pd.Series,
    weights: dict,
    lookback_days: int = 10,
    regression_window: int = 252,
) -> dict:
    """
    For each stock, decompose returns into Market + Sector + Fundamental components.

    stock_prices: DataFrame with stock tickers as columns, daily prices
    spy_prices: SPY daily prices
    sector_etf_prices: sector ETF daily prices
    weights: dict of {ticker: weight_pct}
    lookback_days: period for return calculation (display)
    regression_window: days for regression beta estimation
    """
    # Compute returns
    spy_ret = spy_prices.pct_change().dropna()
    sector_ret = sector_etf_prices.pct_change().dropna()

    # Sector residual: sector return unexplained by market
    common_idx = spy_ret.index.intersection(sector_ret.index)
    spy_r = spy_ret.reindex(common_idx)
    sec_r = sector_ret.reindex(common_idx)

    # Compute sector residual via simple regression
    if len(common_idx) > 30:
        X = spy_r.values
        y = sec_r.values
        mask = ~(np.isnan(X) | np.isnan(y))
        X_clean, y_clean = X[mask], y[mask]
        if len(X_clean) > 10:
            beta_sec_mkt = np.polyfit(X_clean, y_clean, 1)[0]
            sector_residual = sec_r - beta_sec_mkt * spy_r
        else:
            sector_residual = sec_r - spy_r
    else:
        sector_residual = sec_r - spy_r

    results = []
    sector_totals = {"market_pct": 0, "sector_pct": 0, "fundamental_pct": 0, "total_weight": 0}

    for ticker in stock_prices.columns:
        if ticker not in weights:
            continue

        stock_ret = stock_prices[ticker].pct_change().dropna()
        weight = weights[ticker]

        # Align all series
        common = stock_ret.index.intersection(spy_r.index).intersection(sector_residual.index)
        if len(common) < max(30, lookback_days + 1):
            continue

        s = stock_ret.reindex(common)
        m = spy_r.reindex(common)
        sr = sector_residual.reindex(common)

        # Use last regression_window days for beta estimation
        reg_slice = slice(-min(regression_window, len(common)), None)
        s_reg = s.iloc[reg_slice].values
        m_reg = m.iloc[reg_slice].values
        sr_reg = sr.iloc[reg_slice].values

        # Remove NaN
        valid = ~(np.isnan(s_reg) | np.isnan(m_reg) | np.isnan(sr_reg))
        s_v, m_v, sr_v = s_reg[valid], m_reg[valid], sr_reg[valid]

        if len(s_v) < 20:
            continue

        # Multiple regression: stock = alpha + beta_mkt * market + beta_sec * sector_residual + epsilon
        X = np.column_stack([np.ones(len(m_v)), m_v, sr_v])
        try:
            betas, residuals, _, _ = np.linalg.lstsq(X, s_v, rcond=None)
            alpha, beta_mkt, beta_sec = betas

            # R-squared
            y_pred = X @ betas
            ss_res = np.sum((s_v - y_pred) ** 2)
            ss_tot = np.sum((s_v - np.mean(s_v)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            r_squared = max(0, min(1, r_squared))
        except Exception:
            beta_mkt, beta_sec, alpha, r_squared = 1.0, 0.0, 0.0, 0.0

        # Compute lookback-period returns using cumulative daily returns
        lb = min(lookback_days, len(s) - 1)
        stock_total_ret = float(s.iloc[-lb:].sum() * 100) if lb > 0 else 0
        mkt_total_ret = float(m.iloc[-lb:].sum() * 100) if lb > 0 else 0
        sec_total_ret = float(sr.iloc[-lb:].sum() * 100) if lb > 0 else 0

        # Factor attribution for the lookback period
        mkt_contribution = beta_mkt * mkt_total_ret
        sec_contribution = beta_sec * sec_total_ret
        fund_contribution = stock_total_ret - mkt_contribution - sec_contribution

        # Percentages — use variance decomposition (R² based) for stable attribution
        # Market explains R²×(beta_mkt²×var_m / var_s) portion, etc.
        var_m = np.var(m_v) if np.var(m_v) > 0 else 1e-10
        var_sr = np.var(sr_v) if np.var(sr_v) > 0 else 1e-10
        var_s = np.var(s_v) if np.var(s_v) > 0 else 1e-10

        mkt_var_share = (beta_mkt ** 2 * var_m) / var_s
        sec_var_share = (beta_sec ** 2 * var_sr) / var_s
        fund_var_share = max(0, 1 - mkt_var_share - sec_var_share)

        total_share = mkt_var_share + sec_var_share + fund_var_share
        if total_share > 0:
            mkt_pct = mkt_var_share / total_share * 100
            sec_pct = sec_var_share / total_share * 100
            fund_pct = fund_var_share / total_share * 100
        else:
            mkt_pct, sec_pct, fund_pct = 33.3, 33.3, 33.3

        # Accumulate weighted sector totals
        sector_totals["market_pct"] += mkt_pct * weight
        sector_totals["sector_pct"] += sec_pct * weight
        sector_totals["fundamental_pct"] += fund_pct * weight
        sector_totals["total_weight"] += weight

        results.append({
            "ticker": ticker,
            "weight": round(weight, 1),
            "total_return": round(stock_total_ret, 1),
            "total_return_pct": f"{stock_total_ret:+.1f}%",
            "market_pct": round(mkt_pct, 0),
            "sector_pct": round(sec_pct, 0),
            "fundamental_pct": round(fund_pct, 0),
            "market_contribution": round(mkt_contribution, 2),
            "sector_contribution": round(sec_contribution, 2),
            "fundamental_contribution": round(fund_contribution, 2),
            "beta_market": round(beta_mkt, 2),
            "beta_sector": round(beta_sec, 2),
            "r_squared": round(r_squared, 2),
            "alpha": round(alpha * 252 * 100, 2),  # annualized alpha in pct
        })

    # Sort by weight descending
    results.sort(key=lambda x: x["weight"], reverse=True)

    # Normalize sector totals
    tw = sector_totals["total_weight"]
    if tw > 0:
        sector_composition = {
            "market_pct": round(sector_totals["market_pct"] / tw, 0),
            "sector_pct": round(sector_totals["sector_pct"] / tw, 0),
            "fundamental_pct": round(sector_totals["fundamental_pct"] / tw, 0),
        }
    else:
        sector_composition = {"market_pct": 33, "sector_pct": 33, "fundamental_pct": 34}

    return {
        "stocks": results,
        "sector_composition": sector_composition,
    }


def get_sector_holdings_weights(sector_name: str, holdings_data: dict) -> dict:
    """Get holdings weights for a sector from cached holdings data."""
    etf_ticker = SECTOR_ETF_MAP.get(sector_name)
    if not etf_ticker or etf_ticker not in holdings_data:
        return {}

    sector_data = holdings_data[etf_ticker]
    weights = {}
    for h in sector_data.get("holdings", []):
        ticker = h.get("ticker") or h.get("Symbol") or h.get("symbol", "")
        weight = h.get("weight") or h.get("Holding Percent") or h.get("holdingPercent", 0)
        if ticker and weight:
            # Convert to percentage if needed
            w = float(weight)
            if w < 1:
                w *= 100
            weights[ticker] = round(w, 2)

    return weights


def generate_sample_holdings(sector_name: str) -> dict:
    """Generate sample holdings for development/demo when real data unavailable."""
    sample_sectors = {
        "Energy": [
            ("XOM", 30.1), ("CVX", 18.2), ("COP", 6.9), ("WMB", 4.1), ("KMI", 3.4),
            ("EOG", 3.3), ("PSX", 3.2), ("VLO", 3.2), ("SLB", 3.1), ("MPC", 3.1),
            ("OXY", 2.6), ("OKE", 2.5), ("BKR", 2.5), ("TRGP", 2.4), ("FANG", 2.4),
            ("EQT", 1.9), ("TPL", 1.7), ("DVN", 1.3), ("HAL", 1.3), ("EXE", 1.2),
        ],
        "Info Tech": [
            ("AAPL", 22.5), ("MSFT", 20.1), ("NVDA", 12.3), ("AVGO", 5.2), ("CRM", 3.1),
            ("ORCL", 2.8), ("AMD", 2.5), ("CSCO", 2.3), ("ACN", 2.2), ("ADBE", 2.1),
            ("TXN", 1.9), ("INTU", 1.8), ("QCOM", 1.7), ("IBM", 1.5), ("AMAT", 1.4),
            ("NOW", 1.3), ("PANW", 1.2), ("KLAC", 1.1), ("LRCX", 1.0), ("SNPS", 0.9),
        ],
        "Financials": [
            ("BRK-B", 14.2), ("JPM", 11.5), ("V", 8.3), ("MA", 7.1), ("BAC", 4.8),
            ("WFC", 3.4), ("GS", 3.2), ("MS", 3.0), ("SPGI", 2.8), ("AXP", 2.6),
            ("C", 2.3), ("BLK", 2.2), ("PGR", 2.1), ("CB", 1.9), ("MMC", 1.8),
            ("SCHW", 1.7), ("ICE", 1.6), ("AON", 1.5), ("CME", 1.4), ("USB", 1.3),
        ],
        "Health Care": [
            ("LLY", 14.5), ("UNH", 10.2), ("JNJ", 7.8), ("ABBV", 6.5), ("MRK", 5.3),
            ("TMO", 4.1), ("ABT", 3.8), ("PFE", 3.2), ("AMGN", 2.9), ("DHR", 2.7),
            ("ISRG", 2.5), ("BMY", 2.3), ("MDT", 2.1), ("SYK", 1.9), ("GILD", 1.8),
            ("VRTX", 1.7), ("BSX", 1.6), ("CI", 1.5), ("ELV", 1.4), ("ZTS", 1.3),
        ],
    }

    # Default holdings for sectors not explicitly listed
    default = [
        ("STOCK1", 15.0), ("STOCK2", 12.0), ("STOCK3", 10.0), ("STOCK4", 8.0), ("STOCK5", 7.0),
        ("STOCK6", 6.0), ("STOCK7", 5.5), ("STOCK8", 5.0), ("STOCK9", 4.5), ("STOCK10", 4.0),
        ("STOCK11", 3.5), ("STOCK12", 3.0), ("STOCK13", 2.5), ("STOCK14", 2.0), ("STOCK15", 1.8),
        ("STOCK16", 1.6), ("STOCK17", 1.4), ("STOCK18", 1.2), ("STOCK19", 1.0), ("STOCK20", 0.8),
    ]

    holdings = sample_sectors.get(sector_name, default)
    return {ticker: weight for ticker, weight in holdings}
