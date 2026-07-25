"""Underlying spot + underlying-close history for chain-only Massive plans.

The Massive chain snapshot embeds `underlying_asset.price` only on plans with
an indices entitlement; on chain-only plans every contract arrives without it
(the probe reports `underlying_price: false`), and index endpoints like
/v2/aggs/ticker/I:SPX/prev return NOT_AUTHORIZED. Everything downstream keys
off spot (hygiene band, moneyness, gamma sweep, ATM IV), so without a value
the day stays honestly empty.

Fallback source: the S&P 500 index itself (^GSPC) via yfinance — the same
underlying observed at a different vendor, and the dashboard's existing equity
source. This is a real index level, not a proxy or model estimate. The origin
is recorded as `spot_source` in the daily payload so it is never mistaken for
chain-embedded data. If the fallback also fails, no number is invented.

Underlying-close HISTORY (5Y of ^GSPC daily closes) is also sourced here. The
"forward-only, no third-party backfill" rule is an OPTIONS-metric rule (ΔOI,
live vendor IV): it does not apply to the underlying index level, which is a
directly observed series from the same vendor already used for spot. Seeding
that history lets realised vol / VRP compute immediately instead of waiting to
accumulate our own daily closes.
"""

SOURCE_CHAIN = "massive:chain"
SOURCE_YAHOO = "yahoo:^GSPC"


def fetch_spot_fallback():
    """Return (spot, source_label) from yfinance ^GSPC, or (None, None)."""
    try:
        import yfinance as yf
        hist = yf.Ticker("^GSPC").history(period="1d")
        if hist is not None and len(hist):
            close = float(hist["Close"].iloc[-1])
            if close > 0:
                return close, SOURCE_YAHOO
    except Exception as e:
        print(f"[OPTIONS] spot fallback (^GSPC) failed: {e}")
    return None, None


def fetch_underlying_history(period: str = "5y"):
    """Return [(YYYY-MM-DD, close, high, low)] of ^GSPC daily bars over `period`,
    ascending. High/low feed the Parkinson realised-vol estimator. Same
    vendor/series as the live spot fallback. Returns [] on any failure —
    callers keep whatever history they already have; nothing is fabricated.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker("^GSPC").history(period=period, interval="1d")
        if hist is None or not len(hist):
            return []
        out = []
        for ts, row in hist.iterrows():
            close = float(row["Close"]) if row["Close"] else None
            if not close or close <= 0:
                continue
            hi = float(row["High"]) if row.get("High") else None
            lo = float(row["Low"]) if row.get("Low") else None
            out.append((ts.date().isoformat(), close, hi, lo))
        return out
    except Exception as e:
        print(f"[OPTIONS] underlying history (^GSPC) failed: {e}")
        return []


def fetch_today_ohlc():
    """(high, low) of ^GSPC's latest daily bar, or (None, None). Lets the daily
    snapshot store today's high/low for Parkinson vol without a full re-seed."""
    try:
        import yfinance as yf
        hist = yf.Ticker("^GSPC").history(period="1d")
        if hist is not None and len(hist):
            row = hist.iloc[-1]
            hi = float(row["High"]) if row.get("High") else None
            lo = float(row["Low"]) if row.get("Low") else None
            return hi, lo
    except Exception as e:
        print(f"[OPTIONS] today OHLC (^GSPC) failed: {e}")
    return None, None
