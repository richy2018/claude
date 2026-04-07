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
    Also backfills any missing dates since 2026-02-27 on first run.
    """
    today = date.today().isoformat()
    store = _load_store()

    try:
        import yfinance as yf

        earnings = _get_latest_shiller_earnings()
        if earnings is None or earnings <= 0:
            print(f"[PE] No Shiller earnings available to compute PE")
            return store

        # Backfill missing dates if store is sparse
        backfill_start = "2026-02-27"
        existing_dates = set(store.keys())
        if len(existing_dates) < 20:
            # Fetch full history since backfill_start
            print(f"[PE] Backfilling daily PE from {backfill_start}...")
            spx = yf.Ticker("^GSPC")
            hist = spx.history(start=backfill_start)
            if not hist.empty:
                for dt, row in hist.iterrows():
                    d = str(dt.date())
                    if d not in existing_dates:
                        price = float(row["Close"])
                        pe = price / earnings
                        ey = (earnings / price) * 100
                        store[d] = {
                            "pe": round(pe, 2),
                            "ey": round(ey, 4),
                            "price": round(price, 2),
                            "earnings": round(earnings, 4),
                            "source": "backfill",
                            "fetched_at": datetime.now().isoformat(),
                        }
                _save_store(store)
                print(f"[PE] Backfilled {len(store) - len(existing_dates)} days, total {len(store)} entries")
        else:
            # Just fetch today's price
            spx = yf.Ticker("^GSPC")
            hist = spx.history(period="5d")
            if hist.empty:
                print(f"[PE] No price history returned for ^GSPC")
                return store

            price = float(hist["Close"].dropna().iloc[-1])

            # Try .info for trailingPE (works for SPY but not ^GSPC)
            info = spx.info or {}
            pe_yahoo = info.get("trailingPE")

            if pe_yahoo is not None and pe_yahoo > 0:
                pe = pe_yahoo
                ey = (1.0 / pe) * 100
                source = "yahoo_pe"
            else:
                pe = price / earnings
                ey = (earnings / price) * 100
                source = "price_shiller"

            store[today] = {
                "pe": round(pe, 2),
                "ey": round(ey, 4),
                "price": round(price, 2),
                "earnings": round(earnings, 4),
                "source": source,
                "fetched_at": datetime.now().isoformat(),
            }
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
