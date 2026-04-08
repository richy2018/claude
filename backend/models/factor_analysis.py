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

        # Percentages — based on absolute contribution to total return
        abs_total = abs(mkt_contribution) + abs(sec_contribution) + abs(fund_contribution)
        if abs_total > 0.01:
            mkt_pct = abs(mkt_contribution) / abs_total * 100
            sec_pct = abs(sec_contribution) / abs_total * 100
            fund_pct = abs(fund_contribution) / abs_total * 100
        else:
            # Fall back to variance decomposition when returns are near zero
            var_m = np.var(m_v) if np.var(m_v) > 0 else 1e-10
            var_sr = np.var(sr_v) if np.var(sr_v) > 0 else 1e-10
            var_s = np.var(s_v) if np.var(s_v) > 0 else 1e-10
            mkt_share = (beta_mkt ** 2 * var_m) / var_s
            sec_share = (beta_sec ** 2 * var_sr) / var_s
            fund_share = max(0, 1 - mkt_share - sec_share)
            total_share = mkt_share + sec_share + fund_share
            if total_share > 0:
                mkt_pct = mkt_share / total_share * 100
                sec_pct = sec_share / total_share * 100
                fund_pct = fund_share / total_share * 100
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
            "alpha": round(fund_contribution, 2),  # raw alpha = residual return over lookback period
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


def compute_single_stock_decomposition(
    stock_prices: pd.Series,
    spy_prices: pd.Series,
    sector_etf_prices: pd.Series,
    ticker: str,
    lookback_days: int = 10,
    regression_window: int = 252,
) -> dict:
    """
    Decompose a single stock's returns into Market + Sector + Fundamental components.
    Also returns daily historical factor contributions for charting.
    """
    spy_ret = spy_prices.pct_change().dropna()
    sector_ret = sector_etf_prices.pct_change().dropna()

    # Sector residual
    common_idx = spy_ret.index.intersection(sector_ret.index)
    spy_r = spy_ret.reindex(common_idx)
    sec_r = sector_ret.reindex(common_idx)

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

    stock_ret = stock_prices.pct_change().dropna()
    common = stock_ret.index.intersection(spy_r.index).intersection(sector_residual.index)

    if len(common) < max(30, lookback_days + 1):
        return {"error": "Insufficient data for selected lookback."}

    s = stock_ret.reindex(common)
    m = spy_r.reindex(common)
    sr = sector_residual.reindex(common)

    # Beta estimation
    reg_slice = slice(-min(regression_window, len(common)), None)
    s_reg = s.iloc[reg_slice].values
    m_reg = m.iloc[reg_slice].values
    sr_reg = sr.iloc[reg_slice].values

    valid = ~(np.isnan(s_reg) | np.isnan(m_reg) | np.isnan(sr_reg))
    s_v, m_v, sr_v = s_reg[valid], m_reg[valid], sr_reg[valid]

    if len(s_v) < 20:
        return {"error": "Insufficient data for selected lookback."}

    X = np.column_stack([np.ones(len(m_v)), m_v, sr_v])
    try:
        betas, _, _, _ = np.linalg.lstsq(X, s_v, rcond=None)
        alpha, beta_mkt, beta_sec = betas
        y_pred = X @ betas
        ss_res = np.sum((s_v - y_pred) ** 2)
        ss_tot = np.sum((s_v - np.mean(s_v)) ** 2)
        r_squared = max(0, min(1, 1 - ss_res / ss_tot if ss_tot > 0 else 0))
    except Exception:
        beta_mkt, beta_sec, alpha, r_squared = 1.0, 0.0, 0.0, 0.0

    # Lookback period returns
    lb = min(lookback_days, len(s) - 1)
    stock_total_ret = float(s.iloc[-lb:].sum() * 100) if lb > 0 else 0
    mkt_total_ret = float(m.iloc[-lb:].sum() * 100) if lb > 0 else 0
    sec_total_ret = float(sr.iloc[-lb:].sum() * 100) if lb > 0 else 0

    mkt_contribution = beta_mkt * mkt_total_ret
    sec_contribution = beta_sec * sec_total_ret
    fund_contribution = stock_total_ret - mkt_contribution - sec_contribution

    # Historical daily cumulative factor contributions over lookback
    hist_s = s.iloc[-lb:]
    hist_m = m.iloc[-lb:]
    hist_sr = sr.iloc[-lb:]

    daily_mkt = (beta_mkt * hist_m * 100).cumsum()
    daily_sec = (beta_sec * hist_sr * 100).cumsum()
    daily_total = (hist_s * 100).cumsum()
    daily_alpha = daily_total - daily_mkt - daily_sec

    history = []
    dates = hist_s.index
    for i in range(len(dates)):
        dt = dates[i]
        history.append({
            "date": dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt),
            "market": round(float(daily_mkt.iloc[i]), 2),
            "sector": round(float(daily_sec.iloc[i]), 2),
            "alpha": round(float(daily_alpha.iloc[i]), 2),
            "total": round(float(daily_total.iloc[i]), 2),
        })

    return {
        "ticker": ticker,
        "total_return": round(stock_total_ret, 2),
        "total_return_pct": f"{stock_total_ret:+.1f}%",
        "market_contribution": round(mkt_contribution, 2),
        "sector_contribution": round(sec_contribution, 2),
        "fundamental_contribution": round(fund_contribution, 2),
        "beta_market": round(beta_mkt, 2),
        "beta_sector": round(beta_sec, 2),
        "r_squared": round(r_squared, 2),
        "alpha": round(fund_contribution, 2),
        "history": history,
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
        "Materials": [
            ("LIN", 18.5), ("SHW", 9.2), ("FCX", 7.1), ("APD", 6.5), ("ECL", 5.8),
            ("NEM", 5.2), ("CTVA", 4.8), ("DOW", 4.3), ("NUE", 3.9), ("VMC", 3.5),
            ("MLM", 3.2), ("PPG", 3.0), ("DD", 2.8), ("IFF", 2.5), ("CE", 2.3),
            ("EMN", 2.1), ("ALB", 1.9), ("PKG", 1.7), ("IP", 1.5), ("CF", 1.3),
        ],
        "Industrials": [
            ("GE", 10.2), ("CAT", 7.5), ("RTX", 6.8), ("UNP", 5.9), ("HON", 5.5),
            ("DE", 5.0), ("BA", 4.5), ("LMT", 4.1), ("UPS", 3.8), ("ADP", 3.5),
            ("MMM", 3.2), ("WM", 2.9), ("GD", 2.7), ("ITW", 2.5), ("EMR", 2.3),
            ("NOC", 2.1), ("NSC", 1.9), ("CSX", 1.8), ("PH", 1.6), ("TDG", 1.4),
        ],
        "Consumer Disc": [
            ("AMZN", 23.5), ("TSLA", 14.2), ("HD", 8.5), ("MCD", 5.1), ("LOW", 4.3),
            ("NKE", 3.8), ("SBUX", 3.2), ("TJX", 2.9), ("BKNG", 2.7), ("CMG", 2.4),
            ("MAR", 2.1), ("ORLY", 1.9), ("GM", 1.7), ("F", 1.5), ("DHI", 1.4),
            ("ROST", 1.3), ("LEN", 1.2), ("YUM", 1.1), ("HLT", 1.0), ("EBAY", 0.9),
        ],
        "Consumer Staples": [
            ("PG", 15.2), ("COST", 12.5), ("KO", 9.8), ("PEP", 8.5), ("WMT", 7.2),
            ("PM", 5.5), ("MO", 4.1), ("MDLZ", 3.5), ("CL", 3.2), ("TGT", 2.8),
            ("GIS", 2.5), ("STZ", 2.3), ("SYY", 2.1), ("KMB", 1.9), ("HSY", 1.7),
            ("K", 1.5), ("ADM", 1.4), ("MKC", 1.2), ("KHC", 1.1), ("CAG", 1.0),
        ],
        "Comm Services": [
            ("META", 22.5), ("GOOGL", 20.1), ("NFLX", 7.5), ("DIS", 5.2), ("CMCSA", 4.8),
            ("T", 4.3), ("VZ", 3.9), ("TMUS", 3.5), ("CHTR", 3.1), ("EA", 2.8),
            ("ATVI", 2.5), ("MTCH", 2.2), ("WBD", 1.9), ("PARA", 1.7), ("OMC", 1.5),
            ("IPG", 1.3), ("TTWO", 1.2), ("LYV", 1.1), ("FOXA", 1.0), ("NWSA", 0.8),
        ],
        "Utilities": [
            ("NEE", 15.5), ("SO", 9.2), ("DUK", 7.8), ("CEG", 6.5), ("SRE", 5.2),
            ("AEP", 4.8), ("D", 4.3), ("EXC", 3.9), ("XEL", 3.5), ("PEG", 3.2),
            ("ED", 2.9), ("WEC", 2.7), ("AWK", 2.4), ("ES", 2.2), ("DTE", 2.0),
            ("EIX", 1.8), ("AEE", 1.6), ("ETR", 1.5), ("PPL", 1.3), ("CMS", 1.2),
        ],
        "Real Estate": [
            ("PLD", 14.5), ("AMT", 10.2), ("EQIX", 8.5), ("CCI", 6.8), ("PSA", 5.5),
            ("O", 5.0), ("SPG", 4.5), ("WELL", 4.1), ("DLR", 3.8), ("VICI", 3.5),
            ("AVB", 3.2), ("EQR", 2.9), ("ARE", 2.7), ("MAA", 2.5), ("ESS", 2.3),
            ("INVH", 2.1), ("UDR", 1.9), ("KIM", 1.7), ("REG", 1.5), ("HST", 1.3),
        ],
    }

    holdings = sample_sectors.get(sector_name, sample_sectors["Energy"])
    return {ticker: weight for ticker, weight in holdings}
