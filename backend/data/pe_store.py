"""Daily P/E ratio store — fetches from Yahoo Finance, persists to JSON."""

import json
import logging
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).parent / "daily_pe.json"


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


def fetch_and_store_pe() -> dict:
    """
    Fetch current S&P 500 trailing PE from Yahoo Finance,
    store it with today's date, and return the full store.
    """
    today = date.today().isoformat()
    store = _load_store()

    try:
        import yfinance as yf
        spx = yf.Ticker("^GSPC")
        info = spx.info or {}

        pe = info.get("trailingPE")
        price = info.get("regularMarketPreviousClose") or info.get("previousClose")

        if pe is None or pe <= 0:
            logger.warning("Yahoo returned no valid trailingPE for ^GSPC")
            return store

        ey = (1.0 / pe) * 100  # earnings yield in %
        earnings = price / pe if price and pe else None

        entry = {
            "pe": round(pe, 2),
            "ey": round(ey, 4),
            "price": round(price, 2) if price else None,
            "earnings": round(earnings, 4) if earnings else None,
            "fetched_at": datetime.now().isoformat(),
        }

        store[today] = entry
        _save_store(store)
        logger.info(f"Stored daily PE for {today}: PE={pe:.2f}, EY={ey:.2f}%")
        return store

    except ImportError:
        logger.warning("yfinance not installed — skipping PE fetch")
        return store
    except Exception as e:
        logger.error(f"Failed to fetch S&P 500 PE from Yahoo: {e}")
        return store


def get_daily_pe_history() -> dict:
    """Return the full daily PE store (date -> {pe, ey, price, ...})."""
    return _load_store()
