"""Does the publication lag cost you the edge? The decisive diagnostic.

The bias lab (research/bias_lab.py) shows the total flattering margin flips
sign depending on one unknown: how far the liquidity factors genuinely LEAD
equity returns, versus how long the data takes to PUBLISH.

    true lead  <  publication lag   ->  the backtest is inflated; the live
                                        signal cannot capture the move.
    true lead  >  publication lag   ->  lagging costs little or nothing; the
                                        edge survives into production.

Measured crossover in simulation (400 draws, month-indexed, 5F equal weight):

    true lead    total flattering margin (as-built minus honest)
    0 months     +0.060 Sharpe   +0.60% alpha    t = 8.1
    3 months     +0.017 Sharpe   +0.15% alpha    t = 2.3
    6 months     -0.038 Sharpe   -0.44% alpha    t = -5.1
    9 months     -0.002 Sharpe   -0.07% alpha    t = -0.2

So the question that decides whether this model is real is empirical and cheap
to answer: where does each factor's cross-correlation with forward SPY peak?

This module answers it from real data. It needs only the component series and
SPY — no vintages, no BIS archive — so it is runnable the moment network
access exists, well before a full point-in-time rebuild is possible.

Reading the output correctly
----------------------------
Two caveats, both verified against a synthetic world with a known 6-month lead:

1. `use_changes=True` correlates the 6-month DIFFERENCE, matching the mom6
   signal. A difference centred ~3 months back smears the peak later by roughly
   that much, so subtract ~3 from the reported peak lag to read a true lead.
   On the known-6 world the recovered peaks ran 3-13 across factors.

2. A single sample is noisy — peaks move several months between draws. Treat
   the peak lag as a region, not a point, and prefer the shape of the whole
   curve() over the argmax. What matters is not the exact peak but whether the
   correlation is still meaningfully non-zero AT the publication lag, since
   that is the only part a live signal can capture.

Usage:
    from research.leadlag import lead_lag_profile, report
    report(lead_lag_profile(components, spy_monthly))
"""

import numpy as np
import pandas as pd

from research.causal import PUBLICATION_LAG_MONTHS

MAX_LAG = 18


def lead_lag_profile(components, spy_monthly, max_lag=MAX_LAG, use_changes=True):
    """Cross-correlation of each factor against forward SPY returns.

    For lag k, correlate factor[t] with the SPY return over (t, t+1]. A peak at
    k means the factor's reading k months ago best explains this month's
    return — i.e. the factor leads by k.

    Args:
        components: {key: pd.Series} monthly factor levels.
        spy_monthly: monthly SPY close.
        use_changes: correlate the 6-month change (matching the mom6 signal
            transform) rather than the level. Levels in a trending series
            produce spurious correlation.

    Returns:
        {key: {"corr": {lag: r}, "peak_lag": int, "peak_corr": float,
               "pub_lag": int, "tradeable": bool}}
    """
    spy_ret = spy_monthly.resample("MS").last().pct_change().dropna()
    out = {}

    for key, raw in components.items():
        s = raw.dropna()
        if len(s) < 60:
            continue
        s = s.resample("MS").last().ffill()
        x = s.diff(6).dropna() if use_changes else s

        corrs = {}
        for k in range(0, max_lag + 1):
            xl = x.shift(k)
            common = xl.dropna().index.intersection(spy_ret.index)
            if len(common) < 36:
                continue
            a = xl.reindex(common).to_numpy()
            b = spy_ret.reindex(common).to_numpy()
            if np.std(a) < 1e-12 or np.std(b) < 1e-12:
                continue
            corrs[k] = float(np.corrcoef(a, b)[0, 1])

        if not corrs:
            continue

        # Peak by absolute correlation — sign depends on the factor's polarity.
        peak_lag = max(corrs, key=lambda k: abs(corrs[k]))
        pub_lag = PUBLICATION_LAG_MONTHS.get(key, 0)

        out[key] = {
            "corr": corrs,
            "peak_lag": peak_lag,
            "peak_corr": corrs[peak_lag],
            "pub_lag": pub_lag,
            "tradeable": peak_lag >= pub_lag,
            "n": len(spy_ret),
        }

    return out


def report(profile):
    """Print the profile and the verdict per factor."""
    print("=" * 76)
    print("  LEAD-LAG PROFILE — does each factor lead by longer than it lags?")
    print("=" * 76)
    print(f"  {'factor':<24}{'peak lag':>9}{'peak r':>9}{'pub lag':>9}  verdict")
    print("-" * 76)

    for key, d in sorted(profile.items(), key=lambda kv: -abs(kv[1]["peak_corr"])):
        verdict = ("TRADEABLE — leads by more than it lags" if d["tradeable"]
                   else "NOT TRADEABLE — published after the move")
        print(f"  {key:<24}{d['peak_lag']:>9}{d['peak_corr']:>9.3f}"
              f"{d['pub_lag']:>9}  {verdict}")

    print("-" * 76)
    n_bad = sum(1 for d in profile.values() if not d["tradeable"])
    if n_bad:
        print(f"  {n_bad} of {len(profile)} factors peak BEFORE they are published.")
        print("  Their contribution to backtest performance is not reproducible live.")
    else:
        print("  Every factor peaks at or beyond its publication lag.")
        print("  Applying real lags should cost little measured performance.")
    print("=" * 76)


def curve(profile, key):
    """The full correlation-by-lag curve for one factor, for plotting."""
    d = profile.get(key)
    if not d:
        return pd.Series(dtype=float)
    return pd.Series(d["corr"]).sort_index()
