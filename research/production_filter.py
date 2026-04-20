"""
GLI Credit Quality Filter — Production Module
Version: 1.0.0
Rule: A (Credit-Only)
Thresholds: HY OAS percentile < 15, HY OAS 3m change < 10bps

Validation (275 months, 2003-04 to 2026-04, no-filter vs Rule A):
    Rule A Sharpe: ~1.05 (audit-corrected formula) to ~1.23 (pre-audit)
      - 1.049 under arithmetic mean(excess) / std(excess) * sqrt(12)
      - 1.230 under geometric annualized return / annualized vol (no rf)
    Sharpe Δ vs no-filter: +0.15 (both formulas show the same improvement)
    CAPM alpha (Rule A): +4.68% annualized, t-stat 3.22, significant
    Max drawdown: -20.1% (vs SPY B&H -50.8%)

    Note: Earlier documentation reported Sharpe 1.38 / p<0.0001. That figure
    was computed under the pre-audit Sharpe formula (geometric/vol, no rf
    subtraction) on a shorter data window at original publication. The
    post-audit number on current data is materially lower; the strategy's
    risk-adjusted edge is real but smaller than originally advertised.

    Filter trigger rate is low in current data: Rule A fires on ~2 of the
    ~125 historically-eligible Q4/Q5 months. Monte Carlo p-value on the
    Sharpe improvement is not significant (filter sample size too small).
    The strategy's alpha comes primarily from the underlying 5F+mom6 signal
    classification, not from Rule A filtering.

This module is the ONLY place where filter logic lives in production.
All threshold values are defined here as constants, not scattered
across the codebase.
"""

import logging
import numpy as np

logger = logging.getLogger("gli_filter")

# ── Filter Constants (locked from Phase 2 optimization) ──────────────
FILTER_VERSION = "1.0.0"
FILTER_RULE = "A"
FILTER_NAME = "Credit Quality Filter"

HY_OAS_PERCENTILE_THRESHOLD = 15
HY_OAS_3M_CHANGE_THRESHOLD = 10

PERCENTILE_LOOKBACK_MONTHS = 60

DOWNGRADE_FROM = [4, 5]
DOWNGRADE_TO = 3


# ── Computation helpers ──────────────────────────────────────────────

def compute_hy_oas_percentile(hy_oas_current, hy_oas_history):
    """Percentile rank of current HY OAS within trailing 5-year window.

    Args:
        hy_oas_current: current HY OAS level (float)
        hy_oas_history: trailing monthly values (list/array, up to 60)

    Returns:
        float: percentile rank 0-100
    """
    history = np.asarray(hy_oas_history, dtype=float)
    if len(history) == 0:
        return 50.0
    return float(np.sum(history <= hy_oas_current) / len(history) * 100)


def compute_hy_oas_3m_change(hy_oas_current, hy_oas_3m_ago):
    """3-month change in HY OAS, in basis points.

    Args:
        hy_oas_current: current HY OAS (e.g. 4.25)
        hy_oas_3m_ago: HY OAS 3 months prior (e.g. 3.90)

    Returns:
        float: change in bps (positive = widening)
    """
    return (hy_oas_current - hy_oas_3m_ago) * 100


# ── Core filter ──────────────────────────────────────────────────────

def apply_filter(quintile, hy_oas_percentile, hy_oas_3m_change,
                 filter_enabled=True):
    """Apply Rule A credit quality filter to a single signal.

    Args:
        quintile: raw signal quintile (1-5)
        hy_oas_percentile: current HY OAS percentile vs trailing 5y
        hy_oas_3m_change: 3-month change in HY OAS (bps)
        filter_enabled: feature flag

    Returns:
        dict with raw_quintile, filtered_quintile, filter_triggered,
        filter_reason, filter_enabled, hy_oas_percentile, hy_oas_3m_change
    """
    result = {
        "raw_quintile": int(quintile),
        "filtered_quintile": int(quintile),
        "filter_triggered": False,
        "filter_reason": None,
        "filter_enabled": filter_enabled,
        "hy_oas_percentile": round(float(hy_oas_percentile), 1),
        "hy_oas_3m_change": round(float(hy_oas_3m_change), 1),
    }

    if not filter_enabled:
        return result

    if quintile not in DOWNGRADE_FROM:
        return result

    if (hy_oas_percentile < HY_OAS_PERCENTILE_THRESHOLD and
            hy_oas_3m_change < HY_OAS_3M_CHANGE_THRESHOLD):
        result["filtered_quintile"] = DOWNGRADE_TO
        result["filter_triggered"] = True
        result["filter_reason"] = (
            f"HY OAS pctl {hy_oas_percentile:.1f}% < {HY_OAS_PERCENTILE_THRESHOLD}% "
            f"AND 3m chg {hy_oas_3m_change:.0f}bps < {HY_OAS_3M_CHANGE_THRESHOLD}bps"
        )

    return result


# ── Logging ──────────────────────────────────────────────────────────

def log_filter_decision(date, raw_q, filtered_q, triggered, reason,
                        hy_oas_pctl, hy_oas_3m_chg):
    """Log every filter decision for audit trail."""
    if triggered:
        logger.info(
            "FILTER TRIGGERED | %s | Q%d->Q%d | pctl=%.1f%% 3m=%.0fbps | %s",
            date, raw_q, filtered_q, hy_oas_pctl, hy_oas_3m_chg, reason,
        )
    else:
        logger.debug(
            "FILTER PASS | %s | Q%d unchanged | pctl=%.1f%% 3m=%.0fbps",
            date, raw_q, hy_oas_pctl, hy_oas_3m_chg,
        )


# ── Metadata ─────────────────────────────────────────────────────────

def get_filter_metadata():
    """Return filter configuration for display/logging."""
    return {
        "version": FILTER_VERSION,
        "rule": FILTER_RULE,
        "name": FILTER_NAME,
        "thresholds": {
            "hy_oas_percentile": HY_OAS_PERCENTILE_THRESHOLD,
            "hy_oas_3m_change_bps": HY_OAS_3M_CHANGE_THRESHOLD,
        },
        "percentile_lookback_months": PERCENTILE_LOOKBACK_MONTHS,
        "downgrade_from": DOWNGRADE_FROM,
        "downgrade_to": DOWNGRADE_TO,
        # Validation numbers for the CURRENT post-audit code on CURRENT data.
        # Prior claims (Sharpe 1.38, p<0.0001, sharpe_improvement 0.20) were
        # from the pre-audit Sharpe formula (geometric / vol, no rf) on a
        # shorter data window and no longer reproduce — kept here for
        # historical reference under the `legacy_claim` key.
        "validation": {
            "rule_a_sharpe_new_formula": 1.049,
            "rule_a_sharpe_old_formula": 1.230,
            "no_filter_sharpe_new_formula": 0.895,
            "sharpe_improvement_vs_no_filter": 0.15,
            "capm_alpha_annual_pct": 4.68,
            "capm_alpha_tstat": 3.22,
            "capm_alpha_significant": True,
            "max_dd_pct": -20.1,
            "max_dd_vs_spy_bh_pct": -50.8,
            "monte_carlo_significant": False,
            "monte_carlo_note": (
                "Filter trigger rate is low on current data (~2 of 125 "
                "eligible Q4/Q5 months); MC on Sharpe improvement is not "
                "statistically significant at 95% confidence."
            ),
            "backtest_months": 275,
            "backtest_window": "2003-04 to 2026-04",
            "legacy_claim": {
                "sharpe": 1.38,
                "sharpe_improvement": 0.20,
                "return_improvement_pct": 2.37,
                "monte_carlo_p": 0.0001,
                "note": (
                    "Original publication Apr 2026 under pre-audit Sharpe "
                    "formula (geometric / vol, no rf subtraction). Does not "
                    "reproduce under corrected formula or on extended data."
                ),
            },
        },
    }
