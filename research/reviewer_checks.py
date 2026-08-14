"""The three checks the reviewer asked for, in one run.

  1. STATE-FLIP RATE, not quintile migration.
     Of the months that fired defensive on current-vintage data, what share
     also fired defensive as-reported? Quintile migration counts Q1->Q2 as a
     disagreement when both are risk-on, which overstates the problem. The
     overlay only cares about the binary.

  2. THE CLEAN THREE-FACTOR RUN.
     HY OAS, cross-currency basis and Fed funds are never restated, so they
     carry genuine point-in-time integrity with no vintage reconstruction. If
     the 3F version performs comparably to 5F, the vintage problem is retired
     for the overlay's purposes. If the edge only appears once the two
     reconstruction-dependent components are added, that is diagnostic.

     CAVEAT, and it matters: the cross-currency basis series starts 2011-05.
     "60% of the composite with full history" is not right — before 2011 the
     clean set is two factors, not three. The run reports both windows.

  3. UNCONDITIONAL DRAWDOWN BASE RATES.
     From an arbitrary month-start, what fraction of months saw a 5/8/10/15%
     peak-to-trough decline within the next 90 days? Pure price, no vintage
     issues. This is the sizing test the ladder should anchor on.

Plus: M2 revision measured on the TRANSFORM the model uses (YoY growth,
z-scored), not on the level, where 47bn against a 21tn base looks harmless.

Usage:  python3 research/reviewer_checks.py [--index NDX.csv]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from research.causal import expanding_quintiles

DEFENSIVE_Q = 4          # Q4/Q5 = defensive
HORIZON_DAYS = 90
THRESHOLDS = [0.05, 0.08, 0.10, 0.15]


def _snapshot_path():
    for p in (Path("/opt/render/data/full_snapshot.json"),
              ROOT / "research" / "snapshot" / "full_snapshot.json"):
        if p.exists():
            return p
    return None


def _journal_path():
    for p in (Path("/opt/render/data/signal_journal.json"),
              ROOT / "backend" / "data" / "signal_journal.json"):
        if p.exists():
            return p
    return None


def _recs(records):
    if not records:
        return pd.Series(dtype=float)
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["value"].dropna().astype(float).sort_index()


# ---------------------------------------------------------------------------
# 1. State-flip rate
# ---------------------------------------------------------------------------

def state_flip_rate(model="5f"):
    jp = _journal_path()
    if jp is None:
        print("  no journal found — run pit_history.py --seed-journal first")
        return None

    entries = list(json.loads(jp.read_text())["models"].get(model, {}).values())
    pairs = []
    for e in entries:
        fired = e.get("quintile")
        drift = e.get("drift")
        now = drift[-1]["quintile_now"] if drift else fired
        if fired is None or now is None:
            continue
        pairs.append((e["signal_month"], int(fired), int(now)))

    if not pairs:
        print("  no comparable months")
        return None

    n = len(pairs)
    q_moved = sum(1 for _, f, t in pairs if f != t)
    fired_def = [(d, f, t) for d, f, t in pairs if f >= DEFENSIVE_Q]
    now_def = [(d, f, t) for d, f, t in pairs if t >= DEFENSIVE_Q]
    both = [(d, f, t) for d, f, t in pairs if f >= DEFENSIVE_Q and t >= DEFENSIVE_Q]
    state_flips = sum(1 for _, f, t in pairs
                      if (f >= DEFENSIVE_Q) != (t >= DEFENSIVE_Q))

    print(f"  months compared                     : {n}")
    print(f"  quintile migration (the 53% figure) : {q_moved}  ({q_moved/n*100:.1f}%)")
    print(f"  STATE FLIPS (defensive <-> risk-on) : {state_flips}  "
          f"({state_flips/n*100:.1f}%)")
    print()
    print(f"  fired defensive as-reported         : {len(fired_def)}")
    print(f"  fired defensive current-vintage     : {len(now_def)}")
    if now_def:
        agree = len(both) / len(now_def) * 100
        print(f"  of current-vintage defensive fires, {agree:.1f}% also fired "
              f"defensive as-reported")
    if fired_def:
        recall = len(both) / len(fired_def) * 100
        print(f"  of as-reported defensive fires, {recall:.1f}% also fire on "
              f"current-vintage data")
    return {"n": n, "quintile_moved": q_moved, "state_flips": state_flips,
            "fired_def_asreported": len(fired_def), "fired_def_current": len(now_def),
            "both": len(both)}


# ---------------------------------------------------------------------------
# 2. Clean 3F run
# ---------------------------------------------------------------------------

def _z(series, window=36, min_periods=12):
    m = series.rolling(window, min_periods=min_periods).mean()
    sd = series.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    return (((series - m) / sd).clip(-3, 3)) / 3


def clean_factor_run():
    snap_p = _snapshot_path()
    if snap_p is None:
        print("  no full_snapshot.json — run export_snapshot.py first")
        return None
    snap = json.loads(snap_p.read_text())

    from data.hy_spread import load_hy_spread
    hy = load_hy_spread()
    if hy is None:
        print("  backend/data/HY data.csv missing")
        return None

    comps = {}
    comps["spread"] = _z(hy.resample("MS").last().ffill().diff(12))

    fred = {k: _recs(v) for k, v in snap.get("fred", {}).items()}
    rate = fred.get("DFF", fred.get("FEDFUNDS"))
    if rate is not None and len(rate):
        comps["rate"] = _z(rate.resample("MS").last().ffill().diff(6))

    ds = _recs(snap.get("dollar_stress", []))
    if len(ds):
        comps["dollar"] = _z(ds.resample("MS").last().ffill())

    spy = _recs(snap.get("spy", []))
    spy_m = spy.resample("MS").last().ffill()
    spy_ret = spy_m.pct_change().dropna()

    print(f"  component coverage (all never-restated):")
    for k, s in comps.items():
        v = s.dropna()
        print(f"    {k:<8} {v.index[0]:%Y-%m} -> {v.index[-1]:%Y-%m}  ({len(v)} months)")
    print(f"  NOTE: the clean set is 2 factors before {comps['dollar'].dropna().index[0]:%Y-%m}, "
          f"3 after — the basis series does not run the full history.")
    print()

    results = {}
    for label, keys, start in [
        ("2F clean (spread+rate), pre-basis", ["spread", "rate"], None),
        ("3F clean (spread+rate+dollar)", ["spread", "rate", "dollar"], None),
    ]:
        idx = None
        for k in keys:
            s = comps[k].dropna()
            idx = s.index if idx is None else idx.intersection(s.index)
        if idx is None or len(idx) < 60:
            continue
        comp = sum(comps[k].reindex(idx) for k in keys) / len(keys)
        sig = comp.diff(6).dropna()
        q = expanding_quintiles(sig, min_window=36).dropna()

        common = q.index.intersection(spy_ret.index)
        if len(common) < 60:
            continue
        w = q.reindex(common).map(
            {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.10, 5: 0.10}).astype(float).shift(1)
        keep = w.notna()
        w, r = w[keep], spy_ret.reindex(common)[keep]
        port = r * w
        sd = float(port.std())
        sh = float(port.mean()) / sd * np.sqrt(12) if sd > 1e-12 else 0.0
        eq = (1 + port).cumprod()
        dd = float(((eq - eq.expanding().max()) / eq.expanding().max()).min()) * 100
        static = r * float(w.mean())
        sh_s = float(static.mean()) / float(static.std()) * np.sqrt(12)
        results[label] = {"sharpe": sh, "maxdd": dd, "timing": sh - sh_s,
                          "n": len(port), "from": str(port.index[0].date())}
        print(f"  {label:<38} Sharpe {sh:5.3f}  maxDD {dd:6.1f}%  "
              f"vs static {sh - sh_s:+.3f}  (n={len(port)}, from {port.index[0]:%Y-%m})")

    bh = spy_ret.reindex(spy_ret.index[spy_ret.index >= "2006-08-01"])
    print(f"  {'SPY buy & hold':<38} Sharpe "
          f"{float(bh.mean())/float(bh.std())*np.sqrt(12):5.3f}")
    return results


# ---------------------------------------------------------------------------
# 3. Unconditional drawdown base rates
# ---------------------------------------------------------------------------

def drawdown_base_rates(prices, label):
    """From each month-start, worst peak-to-trough decline within 90 days."""
    px = prices.dropna().sort_index()
    month_starts = px.resample("MS").first().dropna().index
    rows = []
    for d in month_starts:
        window = px.loc[d:d + pd.Timedelta(days=HORIZON_DAYS)]
        if len(window) < 20:
            continue
        peak = window.cummax()
        rows.append(float(((window - peak) / peak).min()))
    dd = pd.Series(rows)
    n = len(dd)
    print(f"  {label}: {n} month-starts, {px.index[0]:%Y-%m} -> {px.index[-1]:%Y-%m}")
    print(f"    {'threshold':<12}{'base rate':>11}{'count':>8}")
    out = {}
    for t in THRESHOLDS:
        hit = float((dd <= -t).mean())
        out[t] = hit
        print(f"    {t:>6.0%} decline{hit*100:>10.1f}%{int((dd <= -t).sum()):>8}")
    print(f"    median worst 90d drawdown: {dd.median()*100:.1f}%")
    return out


# ---------------------------------------------------------------------------
# 4. M2 revision on the transform
# ---------------------------------------------------------------------------

def m2_revision_on_transform():
    snap_p = _snapshot_path()
    if snap_p is None:
        print("  no snapshot")
        return None
    snap = json.loads(snap_p.read_text())
    cur = _recs(snap.get("fred", {}).get("M2SL", []))
    first = _recs(snap.get("fred_first_release", {}).get("M2SL", []))
    if not len(cur) or not len(first):
        print("  M2 vintages unavailable")
        return None

    common = cur.index.intersection(first.index)
    a, b = first.reindex(common), cur.reindex(common)

    lvl = (b - a).abs()
    print(f"  LEVEL   : mean |rev| {lvl.mean():.1f}bn on ~{b.mean()/1000:.1f}tn "
          f"= {lvl.mean()/b.mean()*100:.2f}%")

    # The transform the model actually uses: YoY % growth, then z-scored.
    yoy_a = a.pct_change(12) * 100
    yoy_b = b.pct_change(12) * 100
    d_yoy = (yoy_b - yoy_a).dropna()
    print(f"  YoY %   : mean |rev| {d_yoy.abs().mean():.3f}pp vs typical YoY "
          f"level {yoy_b.abs().mean():.2f}pp "
          f"-> {d_yoy.abs().mean()/yoy_b.abs().mean()*100:.1f}% of the signal")

    # 3-month annualised, the reviewer's specific concern.
    ann_a = ((a / a.shift(3)) ** 4 - 1) * 100
    ann_b = ((b / b.shift(3)) ** 4 - 1) * 100
    d_ann = (ann_b - ann_a).dropna()
    print(f"  3m ann.%: mean |rev| {d_ann.abs().mean():.3f}pp vs typical "
          f"{ann_b.abs().mean():.2f}pp "
          f"-> {d_ann.abs().mean()/ann_b.abs().mean()*100:.1f}% of the signal")

    za, zb = _z(yoy_a), _z(yoy_b)
    dz = (zb - za).dropna()
    print(f"  z-scored: mean |rev| {dz.abs().mean():.3f} on a [-1,1] component "
          f"-> {dz.abs().mean()/2*100:.1f}% of full component range")
    return {"level_pct": float(lvl.mean()/b.mean()*100),
            "yoy_share_pct": float(d_yoy.abs().mean()/yoy_b.abs().mean()*100)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", help="CSV of the index to base-rate (date,close). "
                                    "Without it, SPY from the snapshot is used.")
    ap.add_argument("--model", default="5f")
    args = ap.parse_args()

    print("=" * 78)
    print("  1. STATE-FLIP RATE  (the number that decides what we can do next)")
    print("=" * 78)
    state_flip_rate(args.model)

    print()
    print("=" * 78)
    print("  2. CLEAN RUN — components that are never restated")
    print("=" * 78)
    clean_factor_run()

    print()
    print("=" * 78)
    print(f"  3. UNCONDITIONAL DRAWDOWN BASE RATES ({HORIZON_DAYS}d from month-start)")
    print("=" * 78)
    if args.index:
        df = pd.read_csv(args.index)
        df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
        px = df.set_index(df.columns[0])[df.columns[1]].dropna()
        drawdown_base_rates(px, Path(args.index).stem)
    else:
        snap_p = _snapshot_path()
        if snap_p:
            spy = _recs(json.loads(snap_p.read_text()).get("spy", []))
            drawdown_base_rates(spy, "SPY (proxy — pass --index NDX.csv for NDX)")

    print()
    print("=" * 78)
    print("  4. M2 REVISION, measured on the transform the model uses")
    print("=" * 78)
    m2_revision_on_transform()
    print("=" * 78)


if __name__ == "__main__":
    main()
