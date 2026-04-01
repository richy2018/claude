"""Yahoo Finance data fetching module."""

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from ..config import YAHOO_TICKERS, SECTOR_ETFS


def _strip_timezone(index):
    """Strip timezone from DatetimeIndex, keeping local date. Works on all pandas versions."""
    return pd.to_datetime(index.date)


def fetch_yahoo_series(tickers: dict, period: str = "20y", interval: str = "1d") -> pd.DataFrame:
    """Fetch price data for a dict of tickers from Yahoo Finance."""
    ticker_list = list(tickers.keys())
    all_data = {}
    errors = {}

    for ticker in ticker_list:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period, interval=interval)
            if hist.empty:
                errors[ticker] = "No data returned"
                continue
            # Strip timezone immediately per-series to avoid alignment issues
            series = hist["Close"].copy()
            series.index = _strip_timezone(series.index)
            series = series[~series.index.duplicated(keep='last')]
            all_data[ticker] = series
        except Exception as e:
            errors[ticker] = str(e)

    if not all_data:
        raise RuntimeError(f"Failed to fetch any Yahoo data. Errors: {errors}")

    combined = pd.DataFrame(all_data)
    combined.index.name = "date"

    return combined, errors


def fetch_all_yahoo(period: str = "20y") -> tuple:
    """Fetch all Yahoo Finance tickers (market + sector ETFs)."""
    all_tickers = {**YAHOO_TICKERS, **SECTOR_ETFS}
    return fetch_yahoo_series(all_tickers, period=period)


def fetch_sector_holdings() -> dict:
    """Fetch top 20 holdings for each sector ETF."""
    holdings = {}

    for ticker, name in SECTOR_ETFS.items():
        if ticker == "SPY":
            continue
        try:
            etf = yf.Ticker(ticker)
            top = etf.get_funds_data().top_holdings
            if top is not None and not top.empty:
                h = top.head(20).reset_index()
                h.columns = ["ticker", "weight"] if len(h.columns) == 2 else h.columns
                holdings[ticker] = {
                    "sector": name,
                    "holdings": h.to_dict(orient="records"),
                }
            else:
                holdings[ticker] = {"sector": name, "holdings": []}
        except Exception:
            holdings[ticker] = {"sector": name, "holdings": []}

    return holdings
