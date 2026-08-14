"""Point-in-time (vintage) FRED access via ALFRED.

The ordinary FRED observations endpoint returns the CURRENT vintage: every
historical value as it stands today, after all revisions. Backtesting on that
means the model trades on numbers nobody had at the time.

ALFRED is the same API with real-time parameters. Two useful modes:

  initial_release(series_id)
      One request. Returns the FIRST published value for every observation
      date (output_type=4). This is what an observer actually saw at release,
      before any revision. Cheapest meaningful correction, and for most series
      it captures the bulk of the revision effect.

  vintage_as_of(series_id, as_of)
      One request per as-of date. Returns the series exactly as it stood on
      that date, including how far back the data ran. Use when you need to
      reproduce a specific historical decision precisely.

Which series actually need this
-------------------------------
  M2SL            YES. Annual seasonal-factor re-estimation restates history.
  BIS credit      YES, but not available here — BIS publishes no vintage API.
                  Archive each release going forward (see archive_release).
  BAMLH0A0HYM2    No. Market data, not revised.
  DFF / FEDFUNDS  No.

Not exercised against the live API in this environment — outbound access to
api.stlouisfed.org is blocked by egress policy here. The request shapes follow
the documented ALFRED contract; verify against one known revision before
trusting a rebuilt history.
"""

import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# ALFRED output_type codes
_OUTPUT_ALL_VINTAGES = 2
_OUTPUT_INITIAL_ONLY = 4


def _get(params, retries=4):
    """GET with exponential backoff on transport errors."""
    delay = 2
    last = None
    for attempt in range(retries):
        try:
            resp = requests.get(FRED_BASE, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:                       # noqa: BLE001
            last = e
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(f"FRED request failed after {retries} attempts: {last}")


def _to_series(observations, series_id):
    if not observations:
        return pd.Series(dtype=float, name=series_id)
    df = pd.DataFrame(observations)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.set_index("date")["value"].dropna().sort_index()
    s.name = series_id
    return s


def initial_release(series_id, api_key=None, start_date="2000-01-01"):
    """First-published value for each observation date. One request.

    This is the series a real-time observer saw, before revisions.
    """
    key = api_key or os.environ.get("FRED_API_KEY", "")
    if not key:
        raise ValueError("FRED_API_KEY required for ALFRED access")

    data = _get({
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start_date,
        "output_type": _OUTPUT_INITIAL_ONLY,
        "sort_order": "asc",
    })
    return _to_series(data.get("observations", []), series_id)


def vintage_as_of(series_id, as_of, api_key=None, start_date="2000-01-01"):
    """The series exactly as it stood on `as_of` (YYYY-MM-DD). One request."""
    key = api_key or os.environ.get("FRED_API_KEY", "")
    if not key:
        raise ValueError("FRED_API_KEY required for ALFRED access")

    as_of = pd.Timestamp(as_of).strftime("%Y-%m-%d")
    data = _get({
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start_date,
        "realtime_start": as_of,
        "realtime_end": as_of,
        "sort_order": "asc",
    })
    return _to_series(data.get("observations", []), series_id)


def revision_magnitude(series_id, api_key=None, start_date="2000-01-01"):
    """How much did revisions move this series? Diagnostic, two requests.

    Returns a frame of first-published vs current value per date, plus summary
    stats. Run this before deciding whether a series needs PIT treatment —
    if the mean absolute revision is negligible, current vintage is fine.
    """
    key = api_key or os.environ.get("FRED_API_KEY", "")
    first = initial_release(series_id, key, start_date)

    current_raw = _get({
        "series_id": series_id, "api_key": key, "file_type": "json",
        "observation_start": start_date, "sort_order": "asc",
    })
    current = _to_series(current_raw.get("observations", []), series_id)

    common = first.index.intersection(current.index)
    df = pd.DataFrame({"first": first.reindex(common),
                       "current": current.reindex(common)}).dropna()
    df["revision"] = df["current"] - df["first"]
    df["revision_pct"] = df["revision"] / df["first"].replace(0, pd.NA) * 100

    return {
        "frame": df,
        "n": len(df),
        "mean_abs_revision_pct": float(df["revision_pct"].abs().mean()),
        "max_abs_revision_pct": float(df["revision_pct"].abs().max()),
        "pct_revised": float((df["revision"].abs() > 1e-9).mean() * 100),
    }


def archive_release(series, name, archive_dir="research/vintages"):
    """Snapshot a series that has no vintage API (BIS, the basis-swap gist).

    There is no way to recover their history retroactively, so the only path to
    a real point-in-time backtest for these is to start archiving now. Call
    this on every refresh; in a few years the archive IS the vintage database.
    """
    d = Path(archive_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.utcnow().strftime("%Y%m%d")
    path = d / f"{name}_{stamp}.json"

    if path.exists():                                # idempotent per day
        return path

    payload = {
        "name": name,
        "archived_utc": pd.Timestamp.utcnow().isoformat(),
        "observations": [
            {"date": i.strftime("%Y-%m-%d"), "value": None if pd.isna(v) else float(v)}
            for i, v in series.items()
        ],
    }
    path.write_text(json.dumps(payload, indent=1))
    return path


def load_archived_vintage(name, as_of, archive_dir="research/vintages"):
    """Load the most recent archived snapshot at or before `as_of`."""
    d = Path(archive_dir)
    if not d.exists():
        return None
    stamp = pd.Timestamp(as_of).strftime("%Y%m%d")
    candidates = sorted(p for p in d.glob(f"{name}_*.json")
                        if p.stem.rsplit("_", 1)[-1] <= stamp)
    if not candidates:
        return None
    payload = json.loads(candidates[-1].read_text())
    obs = payload["observations"]
    s = pd.Series(
        {pd.Timestamp(o["date"]): o["value"] for o in obs}, dtype=float
    ).dropna().sort_index()
    s.name = name
    return s
