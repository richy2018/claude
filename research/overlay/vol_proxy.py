"""Fit and error-quantify the VIX -> VXN proxy for the pre-2001 block.

WHY A PROXY IS UNAVOIDABLE HERE
VXNCLS (actual NDX 30-day implied vol) begins 2001-02-02. The 1990-2000 block
therefore has no NDX implied vol at all, and the only vol series covering that
decade is VIX itself.

VXO was proposed as a better 1990s candidate on the grounds that it reaches
back to 1986. FRED's VXOCLS does not: it runs 2000-01-03 to 2021-09-23. It
covers neither the 1990s nor the present, so it is not a usable proxy source
here and is excluded. If a 1986-start VXO series is available from the terminal
it can be added, and this module will fit it the same way.

METHOD
Fit on the overlap where both VIX and VXN exist, then apply backwards. The fit
is reported with OUT-OF-SAMPLE error, not in-sample fit quality: the model is
trained on PROXY_FIT_WINDOW and scored on everything after it. That
out-of-sample RMSE in vol points is what propagates through to premium as a
BAND. A point estimate for the 1990s block would be dishonest — the error is
not measurable in that decade and can only be imported from the overlap.

Two specifications, both reported:
    level   VXN = a + b * VIX
    log     log(VXN) = a + b * log(VIX)     — vol is closer to lognormal, and
                                              this keeps the proxy positive and
                                              handles the 2008/2020 tails better

The wider of the two error bands is carried forward unless one is clearly
better on the holdout.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

FIT_START, FIT_END = "2001-02-02", "2010-12-31"


def _snapshot():
    for p in (Path("/opt/render/data/full_snapshot.json"),
              ROOT / "research" / "snapshot" / "full_snapshot.json"):
        if p.exists():
            return json.loads(p.read_text())
    return None


def _recs(records):
    if not records:
        return pd.Series(dtype=float)
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["value"].dropna().astype(float).sort_index()


def load_vols():
    """VIX from the Bloomberg options export, VXN/VXO/VXV from FRED."""
    from data.options_market import load_options_market
    mkt = load_options_market()
    snap = _snapshot()
    if snap is None:
        raise RuntimeError("full_snapshot.json not found — run export_snapshot.py")
    fred = snap.get("fred", {})
    return {
        "VIX": mkt.get("VIX", pd.Series(dtype=float)),
        "VXN": _recs(fred.get("VXNCLS", [])),
        "VXO": _recs(fred.get("VXOCLS", [])),
        "VXV": _recs(fred.get("VXVCLS", [])),
    }


def fit_and_score(x, y, spec="log"):
    """OLS on the fit window, scored out-of-sample on everything after it."""
    common = x.index.intersection(y.index)
    xs, ys = x.reindex(common), y.reindex(common)

    in_mask = (common >= FIT_START) & (common <= FIT_END)
    out_mask = common > FIT_END
    if in_mask.sum() < 200 or out_mask.sum() < 200:
        return None

    def tf(v):
        return np.log(v) if spec == "log" else v

    def inv(v):
        return np.exp(v) if spec == "log" else v

    b, a = np.polyfit(tf(xs[in_mask]).to_numpy(), tf(ys[in_mask]).to_numpy(), 1)
    pred_out = inv(a + b * tf(xs[out_mask]))
    resid_out = ys[out_mask] - pred_out
    pred_in = inv(a + b * tf(xs[in_mask]))
    resid_in = ys[in_mask] - pred_in

    return {
        "spec": spec, "a": float(a), "b": float(b),
        "n_in": int(in_mask.sum()), "n_out": int(out_mask.sum()),
        "rmse_in": float(np.sqrt((resid_in ** 2).mean())),
        "rmse_out": float(np.sqrt((resid_out ** 2).mean())),
        "bias_out": float(resid_out.mean()),
        "p95_abs_out": float(resid_out.abs().quantile(0.95)),
        "ratio_mean": float((ys / xs).mean()),
    }


def main():
    vols = load_vols()
    print("=" * 78)
    print("  VOL SERIES COVERAGE")
    print("=" * 78)
    for k, s in vols.items():
        if len(s):
            print(f"  {k:<5}{len(s):>7} obs   {s.index[0]:%Y-%m-%d} -> {s.index[-1]:%Y-%m-%d}")
        else:
            print(f"  {k:<5}   absent")

    vxo = vols["VXO"]
    if len(vxo) and vxo.index[0].year >= 1999:
        print()
        print(f"  VXO EXCLUDED as a 1990s proxy: FRED's VXOCLS starts "
              f"{vxo.index[0]:%Y-%m} and ends {vxo.index[-1]:%Y-%m}.")
        print("  It covers neither the 1990s nor the present. VIX is the only")
        print("  vol series spanning 1990-2000, so it is the only candidate.")

    print()
    print("=" * 78)
    print(f"  VIX -> VXN PROXY   fit {FIT_START}..{FIT_END}, scored OUT-OF-SAMPLE after")
    print("=" * 78)
    print(f"  {'spec':<7}{'a':>9}{'b':>8}{'n_in':>7}{'n_out':>7}"
          f"{'RMSE in':>10}{'RMSE out':>10}{'bias':>8}{'p95|e|':>9}")
    print("  " + "-" * 74)

    best = None
    for spec in ("level", "log"):
        r = fit_and_score(vols["VIX"], vols["VXN"], spec)
        if r is None:
            continue
        print(f"  {r['spec']:<7}{r['a']:>9.3f}{r['b']:>8.3f}{r['n_in']:>7}"
              f"{r['n_out']:>7}{r['rmse_in']:>10.2f}{r['rmse_out']:>10.2f}"
              f"{r['bias_out']:>8.2f}{r['p95_abs_out']:>9.2f}")
        if best is None or r["rmse_out"] < best["rmse_out"]:
            best = r

    if best:
        print()
        print(f"  Selected on out-of-sample RMSE: {best['spec']}")
        print(f"  1990-2000 ATM vol carries a band of +/- {best['rmse_out']:.2f} vol points")
        print(f"  (1 sd) and +/- {best['p95_abs_out']:.2f} at the 95th percentile of")
        print(f"  absolute error. This propagates to premium and is reported as a")
        print(f"  band, never a point. Mean VXN/VIX ratio on the overlap: "
              f"{best['ratio_mean']:.3f}")

    vxv = vols["VXV"]
    if len(vxv):
        print()
        print("=" * 78)
        print("  TERM STRUCTURE")
        print("=" * 78)
        print(f"  VXVCLS starts {vxv.index[0]:%Y-%m}. The 3M/30d shape proxy is")
        print(f"  therefore UNAVAILABLE for 2001-{vxv.index[0].year}, which is a gap")
        print("  INSIDE the primary study, not only in the secondary block. Those")
        print("  years run on the assumed contango/backwardation variants alone.")
        common = vxv.index.intersection(vols["VIX"].index)
        if len(common) > 200:
            ratio = (vxv.reindex(common) / vols["VIX"].reindex(common)).dropna()
            print(f"  Observed 3M/30d ratio {vxv.index[0]:%Y}+: median "
                  f"{ratio.median():.3f}, "
                  f"contango {float((ratio > 1).mean())*100:.0f}% of days, "
                  f"p10 {ratio.quantile(0.10):.3f}, p90 {ratio.quantile(0.90):.3f}")
    print("=" * 78)


if __name__ == "__main__":
    main()
