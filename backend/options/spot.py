"""Underlying spot fallback for chain-only Massive plans.

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
