"""US equity-options trading-day calendar (NYSE / XNYS).

The snapshot job gates on this so weekends AND NYSE holidays are rejected — a
weekday holiday (the vendor re-serves the prior session) is not a trading day
even though `weekday() < 5`. Uses pandas_market_calendars (XNYS). If the
package is unavailable the check DEGRADES to a weekday test and says so via
`calendar_source()`, so the caller can still gate weekends and never silently
claims holiday-awareness it doesn't have.
"""

import datetime as dt

_cal = None
_cache = {}
_source = None


def _calendar():
    global _cal, _source
    if _cal is None:
        import pandas_market_calendars as mcal   # lazy: pandas only loaded on use
        _cal = mcal.get_calendar("XNYS")
        _source = "XNYS (pandas_market_calendars)"
    return _cal


def calendar_source() -> str:
    """Which calendar actually answered — real NYSE holidays vs weekday fallback."""
    return _source or "weekday-only (pandas_market_calendars unavailable)"


def is_trading_day(date_str: str) -> bool:
    if date_str in _cache:
        return _cache[date_str]
    d = dt.date.fromisoformat(date_str)
    if d.weekday() >= 5:
        _cache[date_str] = False
        return False
    try:
        sched = _calendar().schedule(start_date=date_str, end_date=date_str)
        res = len(sched) > 0
    except Exception:
        global _source
        _source = "weekday-only (pandas_market_calendars unavailable)"
        res = d.weekday() < 5
    _cache[date_str] = res
    return res
