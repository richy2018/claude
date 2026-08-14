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


def lead_lag_profile(components, spy_monthly, max_lag=MAX_LAG, use_changes=True,
                     n_perm=500):
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

        # Is that peak bigger than what searching this many lags finds in noise?
        # Permute the return series, recompute the best |r| across all lags,
        # repeat. The 95th percentile of that distribution is the bar the real
        # peak has to clear. This prices in the lag search directly, which a
        # plain t-test on a single correlation does not.
        null_maxes = _permutation_null(x, spy_ret, max_lag, n_perm)
        observed = abs(corrs[peak_lag])
        if null_maxes is None:
            noise_bar, p_value, significant = np.nan, np.nan, False
        else:
            noise_bar = float(np.percentile(null_maxes, 95))
            p_value = float(np.mean(null_maxes >= observed))
            significant = observed > noise_bar

        out[key] = {
            "corr": corrs,
            "peak_lag": peak_lag,
            "peak_corr": corrs[peak_lag],
            "pub_lag": pub_lag,
            "corr_at_pub_lag": corrs.get(pub_lag),
            "noise_bar_95": noise_bar,
            "p_value": p_value,
            "significant": significant,
            # Only meaningful if there is a peak worth trading in the first place.
            "tradeable": significant and peak_lag >= pub_lag,
            "n": len(spy_ret),
        }

    return out


def _permutation_null(x, spy_ret, max_lag, n_perm, seed=20260814):
    """95th percentile of max|r| across lags when returns are shuffled.

    Shuffling the returns destroys any real relationship while preserving the
    factor's own autocorrelation and the number of lags searched.
    """
    rng = np.random.default_rng(seed)
    common0 = x.dropna().index.intersection(spy_ret.index)
    if len(common0) < 36:
        return None

    base = spy_ret.reindex(common0).to_numpy()
    lag_mats = []
    for k in range(0, max_lag + 1):
        xl = x.shift(k).reindex(common0).to_numpy()
        if np.isfinite(xl).sum() > 36:
            lag_mats.append(xl)

    maxes = np.empty(n_perm)
    for i in range(n_perm):
        shuffled = rng.permutation(base)
        best = 0.0
        for xl in lag_mats:
            m = np.isfinite(xl)
            if m.sum() < 36:
                continue
            a, b = xl[m], shuffled[m]
            if np.std(a) < 1e-12 or np.std(b) < 1e-12:
                continue
            best = max(best, abs(float(np.corrcoef(a, b)[0, 1])))
        maxes[i] = best

    return maxes


def report(profile):
    """Print the profile and the verdict per factor.

    Two hurdles, in order. A factor has to clear BOTH:
      1. Is the peak correlation real at all, once you price in searching
         ~19 lags? (permutation null, 95th percentile bar)
      2. Does the peak sit at or beyond the publication lag, so a live signal
         could actually capture it?
    Failing (1) makes (2) moot — you cannot trade a peak that is noise.
    """
    print("=" * 84)
    print("  LEAD-LAG PROFILE")
    print("=" * 84)
    print(f"  {'factor':<22}{'peak':>6}{'r':>8}{'noise bar':>11}{'p':>7}"
          f"{'pub lag':>9}{'r@pub':>8}  verdict")
    print("-" * 84)

    for key, d in sorted(profile.items(), key=lambda kv: -abs(kv[1]["peak_corr"])):
        if not d["significant"]:
            verdict = "NOISE — peak within the lag-search null"
        elif d["tradeable"]:
            verdict = "TRADEABLE — real and published in time"
        else:
            verdict = "TOO LATE — real but published after the move"
        rp = d.get("corr_at_pub_lag")
        print(f"  {key:<22}{d['peak_lag']:>6}{d['peak_corr']:>8.3f}"
              f"{d['noise_bar_95']:>11.3f}{d['p_value']:>7.2f}"
              f"{d['pub_lag']:>9}{(f'{rp:.3f}' if rp is not None else '-'):>8}  {verdict}")

    print("-" * 84)
    n_sig = sum(1 for d in profile.values() if d["significant"])
    n_trade = sum(1 for d in profile.values() if d["tradeable"])
    print(f"  {n_sig} of {len(profile)} factors have a peak that beats the noise bar.")
    print(f"  {n_trade} of {len(profile)} are both real AND early enough to trade.")
    if n_sig == 0:
        print()
        print("  No factor shows lead-lag structure distinguishable from noise.")
        print("  With no real lead to capture, backtest performance is coming from")
        print("  something other than the factors predicting returns — most likely")
        print("  from reading data before its release date.")
    print("=" * 84)


def curve(profile, key):
    """The full correlation-by-lag curve for one factor, for plotting."""
    d = profile.get(key)
    if not d:
        return pd.Series(dtype=float)
    return pd.Series(d["corr"]).sort_index()
