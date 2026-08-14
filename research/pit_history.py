"""Rebuild the historical GLI triangles from data as it was REPORTED then.

THE GOAL
Every entry and exit on the chart should be the one that would have fired at
the time, using the numbers actually published by that date — not today's
revised numbers run backwards through the model.

HOW FAR THIS GETS
Per component, at 20% weight each:

    spread_signal   HY OAS (Bloomberg export)   market data, never restated
                                                -> ALREADY as-reported
    rate_signal     DFF / FEDFUNDS              administrative rate
                                                -> ALREADY as-reported
    dollar_stress   xccy basis (gist)           market quotes, never restated
                                                -> ALREADY as-reported
    m2_signal       M2SL                        restated yearly (seasonals)
                                                -> RECOVERED via ALFRED
                                                   first-release
    quantity_signal BIS credit                  restated AND rebased; BIS
                                                publishes no vintage API
                                                -> NOT recoverable

So 80% of the composite can be rebuilt from genuinely as-reported values. The
remaining 20% is BIS, which is handled the only honest way available: it is
lagged by its true publication delay, so the signal at month t uses the BIS
print that had been RELEASED by t — while acknowledging that print's value has
since been revised. Every month carries a purity flag saying so.

WHY THE LAG STILL MATTERS FOR THE CLEAN COMPONENTS
"As-reported" is two separate things: the right VALUE, and the right
AVAILABILITY. HY OAS for 2008-11-20 is the same number today as it was then, so
its value is clean — but a monthly signal must still only use months that had
finished. That is what the execution shift handles.

Usage:
    python3 research/pit_history.py                 # rebuild + report
    python3 research/pit_history.py --seed-journal  # also write to the journal
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

from research.causal import PUBLICATION_LAG_MONTHS, expanding_quintiles

def _resolve_snapshot():
    """Prefer the persistent disk, fall back to the repo copy.

    Checks both because the repo working directory is wiped on every Render
    deploy while /opt/render/data is not, and a local checkout has neither.
    """
    for p in (Path("/opt/render/data") / "full_snapshot.json",
              ROOT / "research" / "snapshot" / "full_snapshot.json"):
        if p.exists():
            return p
    return ROOT / "research" / "snapshot" / "full_snapshot.json"


FULL_SNAPSHOT = _resolve_snapshot()
WEIGHTS = {k: 0.20 for k in ["quantity_signal", "m2_signal", "spread_signal",
                             "dollar_stress_signal", "rate_signal"]}
MIN_LIVE = 3


def _records_to_series(records):
    if not records:
        return pd.Series(dtype=float)
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["value"].dropna().astype(float).sort_index()


def _zscore_level(series, window=36, min_periods=12):
    """Rolling z-score of a series as-is, clipped and scaled — gli_engine's
    `_zscore` followed by its `scale` step."""
    m = series.rolling(window, min_periods=min_periods).mean()
    sd = series.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    return (((series - m) / sd).clip(-3, 3)) / 3


def _zscore_signal(monthly, diff_months=12, window=36, min_periods=12):
    """The engine's component transform: N-month difference, then z-score."""
    return _zscore_level(monthly.diff(diff_months), window, min_periods)


def build_pit_components():
    """Assemble each component from the most as-reported source available.

    Returns (components, purity) where purity[key] is "as_reported",
    "first_release" or "revised_but_lagged".
    """
    comps, purity = {}, {}

    # --- clean: market data, never restated -------------------------------
    from data.hy_spread import load_hy_spread
    hy = load_hy_spread()
    if hy is None:
        raise RuntimeError("backend/data/HY data.csv missing — required for the "
                           "credit component")
    comps["spread_signal"] = _zscore_signal(hy.resample("MS").last().ffill())
    purity["spread_signal"] = "as_reported"

    snap = json.loads(FULL_SNAPSHOT.read_text()) if FULL_SNAPSHOT.exists() else {}
    fred = {k: _records_to_series(v) for k, v in snap.get("fred", {}).items()}
    first = {k: _records_to_series(v)
             for k, v in snap.get("fred_first_release", {}).items()}

    rate = fred.get("DFF", fred.get("FEDFUNDS"))
    if rate is not None and len(rate):
        rm = rate.resample("MS").last().ffill()
        comps["rate_signal"] = _zscore_signal(rm, diff_months=6)
        purity["rate_signal"] = "as_reported"

    ds = _records_to_series(snap.get("dollar_stress", []))
    if len(ds):
        # gli_engine z-scores the dollar-stress LEVEL, not a change: the index
        # is already a spread, so its level is the stress reading.
        comps["dollar_stress_signal"] = _zscore_level(ds.resample("MS").last().ffill())
        purity["dollar_stress_signal"] = "as_reported"

    # --- recovered: first published value, before revisions ---------------
    # gli_engine uses YoY PERCENT growth for M2, negated (low growth = tighter),
    # not a level difference.
    def _m2_signal(series):
        yoy = series.resample("MS").last().ffill().pct_change(12) * 100
        return -_zscore_level(yoy)

    m2 = first.get("M2SL")
    if m2 is not None and len(m2):
        comps["m2_signal"] = _m2_signal(m2)
        purity["m2_signal"] = "first_release"
        # Guard the claim: if ALFRED handed back today's values the label would
        # be hollow and the composite would not be point-in-time at all. Report
        # the actual size of the revisions so "first_release" is verified, not
        # asserted.
        cur = fred.get("M2SL")
        if cur is not None and len(cur):
            common = m2.index.intersection(cur.index)
            if len(common) > 24:
                a, b = m2.reindex(common), cur.reindex(common)
                diff = (b - a).abs()
                changed = int((diff > 1e-9).sum())
                print(f"[PIT ] M2SL revisions: {changed}/{len(common)} months "
                      f"differ from today's vintage "
                      f"(mean |rev| {diff.mean():.1f}, max {diff.max():.1f})")
                if changed == 0:
                    print("[PIT ] WARNING: first-release equals current vintage — "
                          "ALFRED returned no revisions. Treat m2_signal as "
                          "REVISED, not point-in-time.")
                    purity["m2_signal"] = "revised_no_vintage_available"
    elif "M2SL" in fred:
        comps["m2_signal"] = _m2_signal(fred["M2SL"])
        purity["m2_signal"] = "revised_no_vintage_available"

    # --- unrecoverable: BIS. Lag it to its real release delay. -------------
    bis = snap.get("bis", {})
    all_sector = _records_to_series(bis.get("all_sector", []))
    private_nf = _records_to_series(bis.get("private_nf", []))
    if len(all_sector) and len(private_nf):
        num = all_sector.resample("MS").last().ffill()
        den = private_nf.resample("MS").last().ffill()      # causal, not spline
        ratio = (num / den).replace([np.inf, -np.inf], np.nan).dropna()
        qty = _zscore_signal(ratio)
        # Only what had been PUBLISHED by month t.
        comps["quantity_signal"] = qty.shift(PUBLICATION_LAG_MONTHS["quantity_signal"])
        purity["quantity_signal"] = "revised_but_lagged"

    return comps, purity


def build_pit_signal(comps):
    """Composite -> mom6 -> expanding quintiles, renormalised over live weight."""
    idx = pd.DatetimeIndex(sorted(set().union(*[set(s.dropna().index)
                                                for s in comps.values()])))
    total = pd.Series(0.0, index=idx)
    live_w = pd.Series(0.0, index=idx)
    n_live = pd.Series(0, index=idx, dtype=int)

    for k, s in comps.items():
        a = s.reindex(idx, method="ffill")
        present = a.notna()
        total = total.add((WEIGHTS[k] * a).where(present, 0.0), fill_value=0.0)
        live_w = live_w.add(pd.Series(WEIGHTS[k], index=idx).where(present, 0.0),
                            fill_value=0.0)
        n_live += present.astype(int)

    comp = (total / live_w.replace(0.0, np.nan)).where(n_live >= MIN_LIVE).dropna()
    signal = comp.diff(6).dropna()
    quintiles = expanding_quintiles(signal, min_window=36).dropna()
    return comp, signal, quintiles, n_live.reindex(quintiles.index)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-journal", action="store_true",
                    help="Write the rebuilt history into the signal journal, "
                         "marked as point-in-time reconstruction.")
    ap.add_argument("--model", default="5f")
    args = ap.parse_args()

    if not FULL_SNAPSHOT.exists():
        # Not relative_to(ROOT): the resolved path may be on the Render
        # persistent disk, which is outside the repo and would raise.
        print(f"Missing {FULL_SNAPSHOT}.")
        print("Run this first, on a host with network and FRED_API_KEY:")
        print("    python -m research.export_snapshot")
        return 1

    comps, purity = build_pit_components()
    comp, signal, quintiles, n_live = build_pit_signal(comps)

    print("=" * 76)
    print("  POINT-IN-TIME HISTORY — signals as they would have fired")
    print("=" * 76)
    print(f"  {'component':<24}{'weight':>8}  provenance")
    print("-" * 76)
    for k in WEIGHTS:
        print(f"  {k:<24}{WEIGHTS[k]:>8.0%}  {purity.get(k, 'MISSING')}")
    print("-" * 76)
    # Report each provenance class by its actual weight. The first version
    # assumed everything not as-reported was BIS, which printed "40% is BIS"
    # on a run where BIS was missing entirely and M2 had silently fallen back
    # to revised values.
    by_class = {}
    for k in WEIGHTS:
        by_class.setdefault(purity.get(k, "MISSING"), 0.0)
        by_class[purity.get(k, "MISSING")] += WEIGHTS[k]

    LABEL = {
        "as_reported": "genuinely as-reported (never restated)",
        "first_release": "as-reported (ALFRED first release)",
        "revised_but_lagged": "revised values, lagged to real release date",
        "revised_no_vintage_available": "REVISED — vintage fetch failed, not point-in-time",
        "MISSING": "MISSING — factor absent, composite is thinner",
    }
    for cls, w in sorted(by_class.items(), key=lambda kv: -kv[1]):
        print(f"  {w:>4.0%}  {LABEL.get(cls, cls)}")

    clean = by_class.get("as_reported", 0) + by_class.get("first_release", 0)
    print(f"  ----")
    print(f"  {clean:.0%} of the composite is point-in-time.")
    impure = [k for k, v in purity.items()
              if v in ("revised_no_vintage_available",)]
    missing = [k for k in WEIGHTS if purity.get(k, "MISSING") == "MISSING"]
    if impure:
        print(f"  NOT point-in-time: {', '.join(impure)} — rerun export_snapshot "
              f"so the ALFRED first-release fetch succeeds.")
    if missing:
        print(f"  ABSENT: {', '.join(missing)} — these months ran without it.")
    print("-" * 76)
    print(f"  Signal spans {signal.index[0]:%Y-%m} to {signal.index[-1]:%Y-%m}")
    print(f"  Quintiles    {quintiles.index[0]:%Y-%m} to {quintiles.index[-1]:%Y-%m} "
          f"({len(quintiles)} months)")

    defensive = quintiles[quintiles >= 4]
    flips = (quintiles >= 4).astype(int).diff().fillna(0)
    entries = flips[flips == 1].index
    exits = flips[flips == -1].index
    print(f"  Defensive months: {len(defensive)}   "
          f"entries (red): {len(entries)}   exits (green): {len(exits)}")
    print("-" * 76)
    print("  Most recent 12 transitions:")
    trans = sorted(list(entries) + list(exits))[-12:]
    for d in trans:
        kind = "RED  enter defensive" if d in entries else "GREEN exit defensive"
        print(f"    {d:%Y-%m}  {kind}   (Q{int(quintiles[d])}, "
              f"{int(n_live.get(d, 0))} live factors)")
    print("=" * 76)

    if args.seed_journal:
        from data.signal_journal import record_many
        batch = [{"signal_month": d.strftime("%Y-%m-%d"),
                  "quintile": int(q),
                  "composite": float(signal.get(d, np.nan))
                  if pd.notna(signal.get(d, np.nan)) else None,
                  "components": {"provenance": purity}}
                 for d, q in quintiles.items()]
        counts = record_many(args.model, batch, as_of_month=None)
        print(f"\nSeeded journal: {counts}")
        print("These are point-in-time RECONSTRUCTIONS, not live observations —")
        print("recorded_live stays false. They are frozen and will not move again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
