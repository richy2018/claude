"""Re-test the GLI edge on the real data snapshot: as-built vs causal.

Inputs are the three files exported from the live Render backend:
    research/bis-credit.json   -> debt_ratio.ratio_series (all component signals)
    research/spy.json          -> SPY daily close
    research/fred.json         -> FRED cache (rf / HY OAS, both short — see below)

WHAT THIS CAN AND CANNOT MEASURE
--------------------------------
CAN:  the publication-lag effect, on real components. Both arms share identical
      inputs, so the DELTA is clean even where the inputs themselves are poor.

CANNOT: the interpolation (spline) effect. ratio_series is the OUTPUT of the
      pipeline, already downstream of the cubic spline, so the snapshot cannot
      separate it. bias_lab.py measures that mechanism separately and finds it
      negligible at the 20% weight the 5F model gives it.

CANNOT: a trustworthy ABSOLUTE restatement of the track record. Two reasons:
      1. The snapshot's FRED cache is truncated, so several components are
         pinned at exactly 0.0 for most of history (see the coverage report the
         script prints first). The "5F" composite is really 3F before 2012-04
         and 4F until 2025-07.
      2. No risk-free series exists before 2019 in the snapshot, so Sharpe is
         computed as excess over 0%. That inflates every arm equally and is
         therefore fine for the delta, wrong for the level.

Read the DELTA columns. Treat the levels as indicative only.

Usage:  python3 research/snapshot_retest.py
"""

import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from research.causal import PUBLICATION_LAG_MONTHS, expanding_quintiles

KEYS_5F = ["quantity_signal", "m2_signal", "spread_signal",
           "dollar_stress_signal", "rate_signal"]
ALLOC = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.10, 5: 0.10}
TAIL_EVENTS = [("GFC", "2007-09-01"), ("Vol Shock Q4-18", "2018-10-01"),
               ("COVID", "2020-02-01"), ("Rate Shock", "2022-01-01")]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

FULL_SNAPSHOT = "research/snapshot/full_snapshot.json"


def _records_to_series(records):
    if not records:
        return pd.Series(dtype=float)
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["value"].dropna().astype(float).sort_index()


def load_full():
    """Rebuild ratio_series from the full-history snapshot, corrected end to end.

    Unlike load(), this does not inherit the deployed backend's ratio_series —
    it recomputes it from raw inputs through the fixed engine, so the credit
    component comes from BAA10Y (real history) instead of a 3-year rolling HY
    OAS window that was zero-filled into a fake neutral.
    """
    sys.path.insert(0, "backend")
    from models.gli_engine import (
        compute_debt_liquidity_ratio, quarterly_to_monthly_causal, pick_credit_spread,
    )

    snap = json.load(open(FULL_SNAPSHOT))
    fred = {k: _records_to_series(v) for k, v in snap.get("fred", {}).items()}
    fred_df = pd.DataFrame(fred)

    spy = _records_to_series(snap.get("spy", []))

    bis = snap.get("bis", {})
    all_sector = _records_to_series(bis.get("all_sector", []))
    private_nf = _records_to_series(bis.get("private_nf", []))
    if all_sector.empty or private_nf.empty:
        raise RuntimeError("full snapshot is missing BIS credit — cannot rebuild the ratio")

    all_sector_m = all_sector.resample("MS").last().ffill()
    private_nf_m = quarterly_to_monthly_causal(
        pd.DataFrame({"pnf": private_nf}))["pnf"].dropna()

    credit, credit_id, _ = pick_credit_spread(fred_df)
    print(f"[REBUILD] credit spread source: {credit_id}")

    result = compute_debt_liquidity_ratio(
        all_sector_m, private_nf_m,
        policy_rate=fred.get("DFF") if "DFF" in fred else fred.get("FEDFUNDS"),
        hy_spread=credit,
        yield_curve=fred.get("T10Y2Y"),
        m2_supply=fred.get("M2SL"),
        dollar_stress=_records_to_series(snap.get("dollar_stress", [])) or None,
    )

    rs = pd.DataFrame(result["ratio_series"])
    rs["date"] = pd.to_datetime(rs["date"])
    rs = rs.set_index("date").sort_index()

    # rf, finally available: FEDFUNDS as a monthly decimal.
    rf = fred.get("FEDFUNDS", fred.get("DFF", pd.Series(dtype=float)))
    rf_m = (rf.resample("MS").last() / 100.0 / 12.0) if len(rf) else None

    return rs, spy, rf_m, credit_id


def load():
    d = json.load(open("research/bis-credit.json"))
    rs = pd.DataFrame(d["debt_ratio"]["ratio_series"])
    rs["date"] = pd.to_datetime(rs["date"])
    rs = rs.set_index("date").sort_index()

    spy = pd.DataFrame(json.load(open("research/spy.json")))
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date")["SPY"].dropna().sort_index()

    return rs, spy


def rebuild_spread_signal(index):
    """Recompute spread_signal from the Bloomberg HY export, on `index`.

    Reproduces gli_engine's transform exactly — monthly last, 12-month change,
    36-month rolling z-score clipped to +/-3, scaled by 3 — so the rebuilt
    component is directly comparable to the four that already had real history.

    Returns None if the export is missing or too short.
    """
    sys.path.insert(0, "backend")
    from data.hy_spread import load_hy_spread, is_usable

    hy = load_hy_spread()
    if not is_usable(hy):
        return None

    sm = hy.resample("MS").last().ffill()
    chg = sm.diff(12)
    m = chg.rolling(36, min_periods=12).mean()
    sd = chg.rolling(36, min_periods=12).std().replace(0, np.nan)
    z = ((chg - m) / sd).clip(-3, 3)
    return (z / 3).reindex(index, method="ffill")


def coverage_report(rs):
    """Print how much of the composite was actually live, era by era."""
    live = rs[KEYS_5F].notna() & (rs[KEYS_5F] != 0)
    print("=" * 78)
    print("  COMPONENT COVERAGE — how much of the 5F composite was real")
    print("=" * 78)
    print(f"  {'component':<24}{'live months':>12}{'first live':>14}{'dead weight':>14}")
    print("-" * 78)
    for k in KEYS_5F:
        col = live[k]
        first = rs.index[col.argmax()].date() if col.any() else None
        dead = (1 - col.mean()) * 100
        print(f"  {k:<24}{int(col.sum()):>12}{str(first):>14}{dead:>13.0f}%")
    print("-" * 78)
    n_live = live.sum(axis=1)
    print("  Composite weight pinned at exactly 0.0 (read as 'neutral'):")
    for lo, hi in [("2006-08", "2012-03"), ("2012-04", "2025-06"), ("2025-07", "2026-08")]:
        seg = n_live.loc[lo:hi]
        if len(seg):
            print(f"    {lo} .. {hi}:  {(5 - seg.mean()) * 20:.0f}% of weight  "
                  f"({seg.mean():.2f} of 5 components live)")
    print("=" * 78)
    print()
    return live


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_signal(rs, keys, apply_lags, renormalise):
    """5F composite -> mom6 -> expanding quintiles.

    renormalise=False reproduces production exactly: a missing component
    contributes 0.0 at full weight, i.e. is read as a neutral signal.
    renormalise=True divides by the weight actually present, so the composite
    means the same thing in every era.
    """
    comps = {}
    for k in keys:
        s = rs[k].copy()
        if apply_lags:
            m = PUBLICATION_LAG_MONTHS.get(k, 0)
            if m:
                s = s.shift(m)
        comps[k] = s

    w = 1.0 / len(keys)
    comp = pd.Series(0.0, index=rs.index)
    wsum = pd.Series(0.0, index=rs.index)
    for k, s in comps.items():
        present = s.notna() & (s != 0) if renormalise else s.notna()
        comp = comp.add((w * s).where(present, 0.0), fill_value=0.0)
        wsum = wsum.add(pd.Series(w, index=rs.index).where(present, 0.0), fill_value=0.0)

    if renormalise:
        comp = (comp / wsum.replace(0.0, np.nan)).dropna()

    signal = comp.diff(6).dropna()
    return expanding_quintiles(signal, min_window=36).dropna()


def backtest(quintiles, spy_monthly_ret, start="2006-08-01"):
    """Backtest with a one-month execution lag.

    Both series carry month-START labels produced by resample("MS").last(), so
    the row labelled 2020-03-01 holds the value observed on 2020-03-31. The
    signal labelled month t therefore knows all of month t, while spy_ret
    labelled month t is the return earned DURING month t. Multiplying them
    directly trades on the month that has already happened.

    Shifting the weight by one month is what makes it a decision: allocate for
    month t+1 using only what was known at the end of month t.
    """
    common = quintiles.index.intersection(spy_monthly_ret.index)
    common = common[common >= pd.Timestamp(start)]
    if len(common) < 36:
        return None
    q = quintiles.reindex(common)
    r = spy_monthly_ret.reindex(common)
    w = q.map(ALLOC).astype(float).shift(1)
    keep = w.notna()
    w, r, q = w[keep], r[keep], q[keep]
    common = common[keep]
    port = r * w                                   # cash leg earns 0 (no rf in snapshot)

    sd = float(port.std())
    sharpe = float(port.mean()) / sd * np.sqrt(12) if sd > 1e-12 else 0.0
    var = float(r.var())
    beta = float(port.cov(r)) / var if var > 1e-12 else 0.0
    alpha = (float(port.mean()) - beta * float(r.mean())) * 12 * 100

    eq = (1 + port).cumprod()
    dd = float(((eq - eq.expanding().max()) / eq.expanding().max()).min()) * 100

    detected = []
    for name, ds in TAIL_EVENTS:
        d0 = pd.Timestamp(ds)
        vals = [int(q[d]) for d in (d0, d0 - pd.DateOffset(months=1)) if d in q.index]
        detected.append(bool(vals) and max(vals) >= 4)

    return {"sharpe": sharpe, "alpha": alpha, "beta": beta, "max_dd": dd,
            "n": len(common), "detected": detected,
            "start": common[0].date(), "end": common[-1].date()}


def main():
    import os
    if os.path.exists(FULL_SNAPSHOT):
        print(f"Using full-history snapshot ({FULL_SNAPSHOT}) — rebuilding the "
              f"ratio through the corrected engine.\n")
        rs, spy, _rf, credit_id = load_full()
        print(f"\nCredit component sourced from: {credit_id}\n")
    else:
        print("Using the API-export snapshot. Run research/export_snapshot.py on a "
              "networked host for full history (rf series, real credit component).\n")
        rs, spy = load()

    # The deployed spread_signal is dead for 96% of history because FRED caps
    # the ICE BofA series at ~3 years. Rebuild it from the Bloomberg export so
    # the composite is genuinely 5-factor for the first time.
    rebuilt = rebuild_spread_signal(rs.index)
    if rebuilt is not None:
        before = int(((rs["spread_signal"].notna()) & (rs["spread_signal"] != 0)).sum())
        rs = rs.copy()
        rs["spread_signal"] = rebuilt
        after = int(rebuilt.notna().sum())
        print(f"\n[RETEST] spread_signal rebuilt from Bloomberg HY export: "
              f"{before} -> {after} live months of {len(rs)}\n")
    else:
        print("\n[RETEST] HY export unusable — spread_signal left as-is.\n")

    coverage_report(rs)

    spy_m = spy.resample("MS").last().ffill()
    spy_ret = spy_m.pct_change().dropna()

    bh_sd = float(spy_ret.loc["2006-08":].std())
    bh_sharpe = float(spy_ret.loc["2006-08":].mean()) / bh_sd * np.sqrt(12)

    print("=" * 78)
    print("  RE-TEST — as-built (no publication lag) vs causal (lags applied)")
    print("=" * 78)
    print("  Sharpe is excess over 0% — the snapshot has no pre-2019 risk-free")
    print("  series. Both arms are treated identically, so read the DELTA.")
    print("-" * 78)
    print(f"  {'variant':<34}{'Sharpe':>9}{'alpha%':>9}{'maxDD%':>9}{'crashes':>9}")
    print("-" * 78)

    results = {}
    for label, renorm in [("5F as configured (0-fill)", False),
                          ("live-only (renormalised)", True)]:
        for lag_label, lags in [("no lag", False), ("lagged", True)]:
            q = build_signal(rs, KEYS_5F, apply_lags=lags, renormalise=renorm)
            m = backtest(q, spy_ret)
            if not m:
                continue
            results[(label, lag_label)] = m
            hits = f"{sum(m['detected'])}/4"
            print(f"  {label + ' / ' + lag_label:<34}{m['sharpe']:>9.3f}"
                  f"{m['alpha']:>9.2f}{m['max_dd']:>9.1f}{hits:>9}")

    print("-" * 78)
    print(f"  {'SPY buy & hold':<34}{bh_sharpe:>9.3f}{0.0:>9.2f}", end="")
    eq = (1 + spy_ret.loc["2006-08":]).cumprod()
    print(f"{float(((eq - eq.expanding().max()) / eq.expanding().max()).min()) * 100:>9.1f}"
          f"{'-':>9}")
    print("-" * 78)

    for label in ["5F as configured (0-fill)", "live-only (renormalised)"]:
        a = results.get((label, "no lag"))
        b = results.get((label, "lagged"))
        if a and b:
            print(f"  PUBLICATION-LAG COST [{label}]:"
                  f"  Sharpe {b['sharpe'] - a['sharpe']:+.3f}"
                  f"   alpha {b['alpha'] - a['alpha']:+.2f}%")

    any_m = next(iter(results.values()))
    print("-" * 78)
    print(f"  Window: {any_m['start']} .. {any_m['end']}  ({any_m['n']} months)")
    print("  Crash detection = signal in Q4/Q5 at or one month before onset:")
    for label, lag_label in results:
        d = results[(label, lag_label)]["detected"]
        marks = "  ".join(f"{n}{'OK' if hit else 'MISS'}"
                          for (n, _), hit in zip(TAIL_EVENTS, d))
        print(f"    {label} / {lag_label}: {marks}")
    print("=" * 78)


if __name__ == "__main__":
    main()
