"""Daily P/E ratio store — fetches S&P 500 price from Yahoo, computes PE using Shiller earnings."""

import json
import logging
from datetime import datetime, date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).parent / "daily_pe.json"
SHILLER_PATH = Path(__file__).parent / "shiller_pe.csv"


def _load_store() -> dict:
    """Load the persistent daily PE store."""
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_store(store: dict):
    """Save the daily PE store to disk."""
    STORE_PATH.write_text(json.dumps(store, indent=2, sort_keys=True))


def _get_latest_shiller_earnings() -> float:
    """Get the most recent non-null earnings value from Shiller CSV."""
    if not SHILLER_PATH.exists():
        return None
    try:
        df = pd.read_csv(SHILLER_PATH, sep="\t")
        earnings = pd.to_numeric(df["Earnings"], errors="coerce").dropna()
        if len(earnings) > 0:
            return float(earnings.iloc[-1])
    except Exception:
        pass
    return None


def fetch_and_store_pe() -> dict:
    """
    Fetch current S&P 500 price from Yahoo Finance, compute PE using
    latest Shiller earnings, store with today's date.
    """
    today = date.today().isoformat()
    store = _load_store()

    try:
        import yfinance as yf

        # Get current S&P 500 price
        spx = yf.Ticker("^GSPC")
        hist = spx.history(period="5d")
        if hist.empty:
            print(f"[PE] No price history returned for ^GSPC")
            return store

        price = float(hist["Close"].dropna().iloc[-1])

        # Also try .info for trailingPE (works for SPY but not ^GSPC)
        info = spx.info or {}
        pe = info.get("trailingPE")

        if pe is not None and pe > 0:
            # Yahoo provided PE directly
            ey = (1.0 / pe) * 100
            earnings = price / pe
            source = "yahoo_pe"
        else:
            # Compute PE from price + Shiller earnings
            earnings = _get_latest_shiller_earnings()
            if earnings is None or earnings <= 0:
                print(f"[PE] No Shiller earnings available to compute PE")
                return store
            pe = price / earnings
            ey = (earnings / price) * 100
            source = "price_shiller"

        entry = {
            "pe": round(pe, 2),
            "ey": round(ey, 4),
            "price": round(price, 2),
            "earnings": round(earnings, 4) if earnings else None,
            "source": source,
            "fetched_at": datetime.now().isoformat(),
        }

        store[today] = entry
        _save_store(store)
        print(f"[PE] Stored for {today}: PE={pe:.2f}, EY={ey:.2f}%, price={price:.0f} ({source})")
        return store

    except ImportError:
        print("[PE] yfinance not installed — skipping PE fetch")
        return store
    except Exception as e:
        print(f"[PE] Failed to fetch S&P 500 PE: {e}")
        return store


def get_daily_pe_history() -> dict:
    """Return the full daily PE store (date -> {pe, ey, price, ...})."""
    return _load_store()
