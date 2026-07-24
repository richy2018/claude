"""Massive.com API client — chain snapshot with pagination + backoff.

Streams the (large) I:SPX chain page by page via `next_url`, yielding one
slim dict per contract; the full chain is never held in memory at once.
Respects rate limits with exponential backoff on 429.
"""

import time

import requests

from .config import MASSIVE_BASE_URL, UNDERLYING, api_key

_TIMEOUT = 45
_MAX_RETRIES = 5
_PAGE_LIMIT = 250


class MassiveError(RuntimeError):
    pass


def _get(session, url, params=None):
    params = dict(params or {})
    params["apiKey"] = api_key()
    last = None
    for attempt in range(_MAX_RETRIES):
        resp = session.get(url, params=params, timeout=_TIMEOUT)
        last = resp
        if resp.status_code == 429:
            time.sleep(2 ** (attempt + 1))
            continue
        if resp.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        return resp
    return last


def _slim(c: dict) -> dict | None:
    """Reduce a raw snapshot contract to the fields we store. Returns None if
    the contract lacks the identity fields needed to key it."""
    det = c.get("details") or {}
    ticker = det.get("ticker") or c.get("ticker")
    strike = det.get("strike_price")
    expiry = det.get("expiration_date")
    ctype = det.get("contract_type")
    if not (ticker and strike and expiry and ctype):
        return None
    day = c.get("day") or {}
    greeks = c.get("greeks") or {}
    ua = c.get("underlying_asset") or {}
    return {
        "ticker": ticker,
        "strike": float(strike),
        "expiry": expiry,
        "ctype": str(ctype).lower(),
        "oi": c.get("open_interest"),
        "volume": day.get("volume"),
        "iv": c.get("implied_volatility"),
        "delta": greeks.get("delta"),
        "gamma": greeks.get("gamma"),
        "spot": ua.get("price") or ua.get("value"),
    }


def iter_chain_snapshot(underlying: str = UNDERLYING, extra_params: dict | None = None):
    """Yield slim contract dicts for the full chain snapshot, page by page.

    Server-side filters (strike range / expiration_date / contract_type) can be
    passed via extra_params where a caller wants a narrower pull; the daily
    snapshot pulls the full chain so band/stale exclusions can be *reported*,
    not silently never-seen.
    """
    if not api_key():
        raise MassiveError("MASSIVE_API_KEY is not set in the environment")
    session = requests.Session()
    url = f"{MASSIVE_BASE_URL}/v3/snapshot/options/{underlying}"
    params = {"limit": _PAGE_LIMIT}
    params.update(extra_params or {})
    pages = 0
    while url:
        resp = _get(session, url, params)
        if resp is None or resp.status_code != 200:
            code = resp.status_code if resp is not None else "no-response"
            raise MassiveError(f"chain snapshot failed: HTTP {code} on page {pages + 1}")
        payload = resp.json()
        for c in payload.get("results", []) or []:
            slim = _slim(c)
            if slim:
                yield slim
        pages += 1
        url = payload.get("next_url")
        params = {}  # next_url already carries the cursor; apiKey re-added in _get
    if pages == 0:
        raise MassiveError("chain snapshot returned no pages")
