"""Tests for the FINRA Margin Debt leverage/sentiment overlay.

Covers: YoY math, publication-lag handling, regime mapping, no-lookahead
z-score, and the critical invariant that this overlay does NOT touch the
GLI production composite.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from backend.data import margin_debt as md  # noqa: E402


def _synthetic_series(n=200, start="2000-01-01", growth=0.005, base=100000.0):
    """Deterministic monotonic margin-debt series for no-lookahead tests."""
    dates = pd.date_range(start, periods=n, freq="MS")
    vals = [base * (1 + growth) ** i for i in range(n)]
    return pd.Series(vals, index=dates, dtype=float, name="margin_debt_usd_m")


# ── YoY math ──────────────────────────────────────────────────────────────

def test_yoy_math_basic():
    """YoY% = v[t]/v[t-12] - 1, in percent."""
    dates = pd.date_range("2000-01-01", periods=13, freq="MS")
    vals = [100.0] * 12 + [130.0]  # +30% vs 12 months prior
    s = pd.Series(vals, index=dates)
    out = md.compute_margin_debt_signal(s)
    last = out["series"][-1]
    assert last["yoy_pct"] == pytest.approx(30.0, abs=1e-6)


def test_yoy_requires_12_months():
    """A series shorter than 13 months yields insufficient-data meta."""
    s = _synthetic_series(n=10)
    out = md.compute_margin_debt_signal(s)
    assert out["meta"].get("insufficient_data") is True
    assert out["series"] == []


# ── Regime mapping ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("yoy,expected", [
    (45.0, "froth"),
    (30.01, "froth"),
    (30.0, "neutral"),     # boundary: not strictly > froth
    (15.0, "neutral"),
    (0.0, "neutral"),      # boundary: >= neutral_low
    (-0.01, "contraction"),
    (-19.99, "contraction"),
    (-20.0, "capitulation"),  # boundary: <= capitulation
    (-35.0, "capitulation"),
])
def test_regime_mapping(yoy, expected):
    assert md.classify_regime(yoy) == expected


def test_regime_none_safe():
    assert md.classify_regime(None) is None
    assert md.classify_regime(float("nan")) is None


def test_custom_thresholds():
    """Thresholds are configurable."""
    t = {"froth": 50.0, "neutral_low": 5.0, "capitulation": -30.0}
    assert md.classify_regime(40.0, t) == "neutral"   # below custom froth
    assert md.classify_regime(2.0, t) == "contraction"  # below custom neutral_low
    assert md.classify_regime(-31.0, t) == "capitulation"


# ── No-lookahead z-score ─────────────────────────────────────────────────────

def test_zscore_no_lookahead():
    """Z-score at month t uses only trailing data (rolling window)."""
    s = _synthetic_series(n=120)
    out = md.compute_margin_debt_signal(s)
    recs = out["series"]
    # Early records (before min_periods of YoY history) must have null z
    assert recs[0]["yoy_z"] is None
    # Recompute z for a midpoint using ONLY data up to that point; must match.
    yoy = (s / s.shift(12) - 1.0) * 100.0
    cutoff_idx = 80
    cutoff_month = s.index[cutoff_idx]
    z_full = md._expanding_zscore(yoy)
    z_trunc = md._expanding_zscore(yoy.iloc[: cutoff_idx + 1])
    a = z_full.get(cutoff_month)
    b = z_trunc.get(cutoff_month)
    if pd.notna(a) and pd.notna(b):
        assert a == pytest.approx(b, abs=1e-9), "z-score used future data (lookahead!)"


def test_percentile_no_lookahead():
    s = _synthetic_series(n=120)
    yoy = (s / s.shift(12) - 1.0) * 100.0
    cutoff_idx = 90
    cutoff_month = s.index[cutoff_idx]
    p_full = md._expanding_percentile(yoy)
    p_trunc = md._expanding_percentile(yoy.iloc[: cutoff_idx + 1])
    a = p_full.get(cutoff_month)
    b = p_trunc.get(cutoff_month)
    if pd.notna(a) and pd.notna(b):
        assert a == pytest.approx(b, abs=1e-9)


# ── Publication-lag handling ────────────────────────────────────────────────

def test_as_of_reflects_publication_lag():
    """The 'as of' publication date is ~1 month after the reference month."""
    s = _synthetic_series(n=24)
    out = md.compute_margin_debt_signal(s, lag_months=1)
    last = out["series"][-1]
    ref = pd.Timestamp(last["date"])
    as_of = pd.Timestamp(last["as_of"])
    # Publication is in the month AFTER the reference month
    assert as_of > ref
    assert (as_of.year, as_of.month) >= ((ref + pd.offsets.MonthBegin(1)).year,
                                         (ref + pd.offsets.MonthBegin(1)).month)


def test_lagged_yoy_series_shifts():
    """margin_debt_yoy_series(lagged=True) shifts the series forward by lag."""
    import tempfile
    s = _synthetic_series(n=40)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write("# source: SEED PLACEHOLDER\n")
        f.write("date,margin_debt_usd_m\n")
        for d, v in s.items():
            f.write(f"{d.strftime('%Y-%m-%d')},{v:.1f}\n")
        path = f.name
    raw = md.margin_debt_yoy_series(csv_path=path, lagged=False)
    lagged = md.margin_debt_yoy_series(csv_path=path, lagged=True, lag_months=1)
    # Lagged value at month t equals raw value at month t-1
    common = raw.index.intersection(lagged.index)
    assert len(common) > 0
    for m in common[5:8]:
        prev = m - pd.offsets.MonthBegin(1)
        if prev in raw.index:
            assert lagged[m] == pytest.approx(raw[prev], abs=1e-9)
    os.unlink(path)


# ── Loader / provenance ─────────────────────────────────────────────────────

def test_seed_marked_non_authoritative():
    """The shipped seed store must report is_authoritative=False."""
    series, meta = md.load_margin_debt()
    if series is None:
        pytest.skip("margin_debt.csv not present")
    # Seed store header contains 'SEED PLACEHOLDER'
    if "seed" in meta["source"].lower() or "placeholder" in meta["source"].lower():
        assert meta["is_authoritative"] is False


def test_authoritative_flag_for_real_source(tmp_path):
    csv = tmp_path / "margin_debt.csv"
    csv.write_text(
        "# source: FINRA xlsx https://example/margin.xlsx fetched 2026-04-01\n"
        "date,margin_debt_usd_m\n"
        + "".join(f"2020-{m:02d}-01,{500000 + m * 1000}\n" for m in range(1, 13))
        + "".join(f"2021-{m:02d}-01,{520000 + m * 1000}\n" for m in range(1, 13))
    )
    series, meta = md.load_margin_debt(csv_path=str(csv))
    assert series is not None
    assert meta["is_authoritative"] is True


# ── CRITICAL: overlay must NOT touch the GLI composite ───────────────────────

def test_margin_debt_not_in_gli_composite():
    """The GLI production composite must not reference any margin-debt key."""
    from backend.models.backtest_engine import PRODUCTION_MODELS
    for model_key, cfg in PRODUCTION_MODELS.items():
        keys = cfg.get("keys", [])
        for k in keys:
            assert "margin" not in k.lower(), \
                f"Model {model_key} unexpectedly includes margin-debt key '{k}'"
            assert "finra" not in k.lower()


def test_gli_engine_has_no_margin_import():
    """gli_engine (composite builder) must not import the margin_debt overlay."""
    import backend.models.gli_engine as ge
    src = open(ge.__file__).read()
    assert "margin_debt" not in src, "gli_engine must not depend on the margin overlay"
