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

def load():
    d = json.load(open("research/bis-credit.json"))
    rs = pd.DataFrame(d["debt_ratio"]["ratio_series"])
    rs["date"] = pd.to_datetime(rs["date"])
    rs = rs.set_index("date").sort_index()

    spy = pd.DataFrame(json.load(open("research/spy.json")))
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date")["SPY"].dropna().sort_index()

    return rs, spy


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
    common = quintiles.index.intersection(spy_monthly_ret.index)
    common = common[common >= pd.Timestamp(start)]
    if len(common) < 36:
        return None
    q = quintiles.reindex(common)
    r = spy_monthly_ret.reindex(common)
    w = q.map(ALLOC).astype(float)
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
    rs, spy = load()
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
