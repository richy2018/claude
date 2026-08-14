"""PRE-REGISTERED SPECIFICATION — NDX put overlay, signal-conditional test.

FROZEN. Committed before any conditional result exists, at n = 0 journal-era
signals. The whole value of this file is its commit date: it is the only moment
at which pre-registration costs nothing, because there is no result yet to
rationalise around.

Amendment rule: this file may be changed, but every change must be a separate
commit whose message states what changed, why, and confirms whether any
conditional result had been observed at the time. A silent edit voids the
exercise. If you find yourself editing DECISION_THRESHOLD after seeing a
number, stop.

STATUS AT FREEZE
    journal-era signals available : 0
    first genuinely live signal   : 2026-09 (2026-08 was seeded as backfill)
    reconstruction quintile drift : 53.3% of months land in a different
                                    quintile on as-reported inputs, 20.0% flip
                                    defensive <-> risk-on. The reconstruction
                                    is therefore treated as a DIFFERENT SIGNAL,
                                    not as an upper bound on this one, and its
                                    results are never pooled with journal-era
                                    results or placed in the same table.
"""

# ---------------------------------------------------------------------------
# Instrument and strategy
# ---------------------------------------------------------------------------

UNDERLYING = "NDX"
TENOR_MONTHS = 3

# Four INDEPENDENT single-delta series, not a ladder and not a basket. The
# question is "which delta is right", which a blend cannot answer.
DELTAS = [40, 25, 15, 10]

# Each delta series is sized to the SAME PREMIUM BUDGET, not the same notional,
# so results are comparable per euro spent.
SIZING = "equal_premium_budget"

# A basket is permitted for one summary line only, graduated toward the near
# strikes, and must be labelled illustrative.
ILLUSTRATIVE_BASKET_WEIGHTS = {40: 0.50, 25: 0.30, 15: 0.15, 10: 0.05}

# Both roll variants are required; they have different breakevens and the
# comparison between them is itself a deliverable.
ROLL_VARIANTS = {
    # The programme the reviewer's base rate describes.
    "always_on": {"tranches": 3, "fraction_per_month": 1 / 3, "roll": "perpetual"},
    # The programme actually under consideration.
    "fire_only": {"tranches": 1, "fraction_per_month": 1.0, "roll": "none"},
}

# ---------------------------------------------------------------------------
# Monetisation
# ---------------------------------------------------------------------------

# PRIMARY rule. Fixed in advance. Chosen because inverting the reviewer's
# breakeven (p = premium / gross payout; 1.7% / 0.30 = 5.7% gross = ~3.35x
# premium) is most consistent with monetising around the -10% rung. If the
# payoff engine does not reproduce ~30% at this rule, the reviewer's premium
# assumption differs from ours and that discrepancy is reported, not absorbed.
PRIMARY_MONETISATION = "first_touch_-10pct"

# Full sensitivity set. All reported; the primary is not re-chosen after seeing
# which performs best.
MONETISATION_RULES = [
    "first_touch_-5pct",
    "first_touch_-8pct",
    "first_touch_-10pct",
    "first_touch_-15pct",
    "in_life_trough",          # unattainable in practice; upper bound only
    "settled_at_expiry",
    "two_tranche_half_-8_half_-15",
]

# All decline measurement is from the ENTRY LEVEL at t=0. Running-maximum
# drawdown is banned anywhere in the P&L path: a put struck at entry pays on
# the move from entry, not from a high it never traded at. On NDX 1990-2026 the
# running-high convention overstates threshold frequency by 1.42x to 1.73x.
DECLINE_REFERENCE = "entry_level"

# ---------------------------------------------------------------------------
# Execution — applied at 0x, 1x and 2x so the edge's execution-sensitivity is visible
# ---------------------------------------------------------------------------

ENTRY_SLIPPAGE_VOLPTS = {"NDX": 1.0, "QQQ": 0.5}     # through mid, 3M 25-delta

# Exit spread widens with vol, because monetisation happens precisely when
# spreads are widest. A constant-spread model overstates the monetisation edge.
def exit_spread_volpts(atm_iv):
    return 1.0 + 0.06 * max(atm_iv - 20.0, 0.0)      # 20 vol -> 1.0; 50 vol -> 2.8

COMMISSION_PCT_NOTIONAL_PER_SIDE = 0.0003            # 0.03%
FILL_ASSUMPTION = "pay_offer_on_entry_hit_bid_on_exit"   # no mid-fills anywhere
SLIPPAGE_MULTIPLIERS = [0.0, 1.0, 2.0]

# ---------------------------------------------------------------------------
# Vol reconstruction
# ---------------------------------------------------------------------------

# Primary study uses actual VXN. The 1990s block uses a proxy fitted on the
# 2001-2010 overlap and applied backwards, carried as a BAND from the
# out-of-sample RMSE, never as a point estimate.
ATM_VOL_SOURCE = {"primary": "VXN", "secondary_pre2001": "proxy_from_VIX_or_VXO"}
PROXY_FIT_WINDOW = ("2001-01-01", "2010-12-31")
PROXY_CANDIDATES = ["VIX", "VXO"]        # VXO often better for the tail rungs
BLOCKS_NEVER_POOLED = True

# 3M vs 30-day requires an assumption; the whole analysis runs under both.
TERM_STRUCTURE_VARIANTS = ["contango", "backwardation"]

# SKEW -> smile slope. The mapping is validated at the gate below by comparing
# implied 25-delta put vol premium over ATM against Bloomberg OVDV.
SKEW_MAPPING_TOLERANCE_VOLPTS = 1.5      # exceed on any gate date -> stop

# ---------------------------------------------------------------------------
# Validation gate — nothing downstream is computed until this passes
# ---------------------------------------------------------------------------

# Chosen for SKEW dispersion relative to VIX, not regime spread: the parameter
# under test is the skew mapping. ATM level comes from VXN directly and is the
# part least likely to be wrong.
VALIDATION_DATES_RATIONALE = [
    "low-vol / high-SKEW (2017, SKEW ~150 vs VIX ~10) — hardest case",
    "low-vol / low-SKEW  — contrast",
    "2020-03-16 — vol extreme, skew compressed, tests the flattening term",
    "2018-02-06 — fast spike from a low base",
    "2025-04-07 — recent, sanity-checkable by eye",
    "2008-10 — only if OVDV history reaches; otherwise say so, do not substitute",
]
GATE_OUTPUT_COLUMNS = ["date", "strike", "atm_iv", "put_25d_iv",
                       "put_25d_minus_atm", "skew_index", "premium"]

# ---------------------------------------------------------------------------
# Statistics and the decision
# ---------------------------------------------------------------------------

# 3M windows at monthly frequency overlap ~3x. Effective sample is reported on
# non-overlapping quarters; intervals come from a block bootstrap with block
# length >= the window, never iid resampling.
BLOCK_BOOTSTRAP_MIN_BLOCK_MONTHS = TENOR_MONTHS
BOOTSTRAP_DRAWS = 10000
CONFIDENCE = 0.95

# Reported by decade and by entry-VIX quintile, not pooled only — drawdowns
# cluster in regimes and a pooled mean hides that.
STRATIFY_BY = ["decade", "entry_vix_quintile"]

TEST_STATISTIC = (
    "mean per-fire P&L, expressed as % of index notional, signal-conditional "
    "minus blind, under PRIMARY_MONETISATION and 1x slippage"
)

# The decision threshold is set NOW, before any conditional number exists.
DECISION_THRESHOLD = (
    "Adopt the signal-conditional overlay only if the lower bound of the 95% "
    "block-bootstrap interval on TEST_STATISTIC is strictly greater than zero, "
    "on journal-era signals alone, at or beyond the sample size given by "
    "REQUIRED_FIRES. Reconstruction-era results cannot satisfy this."
)

# Filled by the power calculation; see research/overlay/power.py. Recorded here
# so the target is fixed before data accumulates.
# Set by research/overlay/power.py at the primary rung (-10%, blind p0=23.1%,
# NDX 2001+, entry-anchored). 133 fires is the Bernoulli FLOOR for detecting a
# 50% relative lift at 80% power — roughly 33 years at 4 fires/yr. The true
# requirement is higher once payoff dispersion and serially dependent fires are
# accounted for. Frozen here so the target cannot drift once collection starts.
REQUIRED_FIRES = 133
REQUIRED_FIRES_BASIS = "50% relative lift, 23.1% -> 34.7%, 80% power, alpha 0.05"
POWER = 0.80
ALPHA = 0.05

# ---------------------------------------------------------------------------
# What counts as a fire
# ---------------------------------------------------------------------------

SIGNAL_SOURCE = "backend/data/signal_journal.json"
SIGNAL_MODEL = "5f"
FIRE_CONDITION = "quintile >= 4 on the 1st of the month"   # Q4/Q5 = defensive
# Journal entries only, never recomputed. recorded_live=True for the primary
# arm; recorded_live=False entries are reconstruction and are reported in a
# separate descriptive section with the 53.3% migration figure printed adjacent.
PRIMARY_ARM_REQUIRES = "recorded_live == True"
