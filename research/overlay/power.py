"""How many fires are needed to detect a signal-conditional edge?

Answered at n = 0, before collection starts, because the answer determines
whether collection is worth starting at all.

METHOD AND WHY IT NEEDS NO OPTION PRICES
Per-fire P&L on a long put is approximately Bernoulli in premium units: you
lose the premium unless the monetisation event triggers, in which case you
receive gross payout G premiums. Write p for the trigger probability.

    P&L per fire (premiums) = G * I - 1,   I ~ Bernoulli(p)
    mean = pG - 1
    sd   = G * sqrt(p(1-p))

The signal is claimed to lift the trigger rate from p0 (blind) to p1
(conditional). Testing that lift with a two-sided z-test at level ALPHA and
power POWER needs

    n = (z_{1-ALPHA/2} + z_POWER)^2 * p1(1-p1) / (p1 - p0)^2

G cancels. So the required sample depends only on the base rate and the size
of the lift — not on option prices, not on the vol reconstruction, and not on
anything still blocked. That is why this can be produced today.

WHY THE ANSWER IS A FLOOR, NOT AN ESTIMATE
Three effects all push the true requirement higher:

  1. Payoff dispersion. Hits do not all pay G. Real per-fire P&L has variance
     above the Bernoulli approximation, and the test statistic is mean P&L,
     not hit rate.
  2. Serial dependence. Defensive spans run a median of 4 months, so
     consecutive fires are neither independent draws nor independent windows —
     their 3-month horizons overlap. Effective n is below raw fire count.
  3. One-sided framing. Treating the blind arm as a known constant is
     generous; it too is estimated, on ~102 effective quarters.

Read the output as "no fewer than this", and expect the honest number to be
meaningfully larger.
"""

import numpy as np
from scipy import stats

ALPHA = 0.05
POWER = 0.80

# Blind trigger rates, NDX 2001+, first touch measured from ENTRY level.
# Source: research/reviewer_checks.py, entry-anchored — not running-high.
BLIND_RATES = {"-5%": 0.440, "-8%": 0.300, "-10%": 0.231, "-15%": 0.124}

# Plausible fire frequencies for a monthly defensive signal.
FIRES_PER_YEAR = [2, 4, 6]


def required_n(p0, p1, alpha=ALPHA, power=POWER):
    """Fires needed to detect a lift from p0 to p1. Bernoulli floor."""
    if p1 <= p0:
        return np.inf
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    return (z_a + z_b) ** 2 * p1 * (1 - p1) / (p1 - p0) ** 2


def table(rung="-10%"):
    p0 = BLIND_RATES[rung]
    print(f"Rung {rung}: blind trigger rate p0 = {p0:.1%} (NDX 2001+, from entry)")
    print(f"Detecting a lift to p1 at {POWER:.0%} power, alpha {ALPHA}\n")
    print(f"  {'p1':>7}{'rel lift':>10}{'fires needed':>14}" +
          "".join(f"{f'@{f}/yr':>10}" for f in FIRES_PER_YEAR))
    print("  " + "-" * (31 + 10 * len(FIRES_PER_YEAR)))
    for mult in (1.25, 1.5, 1.75, 2.0, 2.5):
        p1 = min(p0 * mult, 0.95)
        n = required_n(p0, p1)
        yrs = "".join(f"{n/f:>9.0f}y" for f in FIRES_PER_YEAR)
        print(f"  {p1:>6.1%}{mult:>9.2f}x{n:>14.0f}{yrs}")
    print()


def main():
    print("=" * 74)
    print("  POWER — fires required to detect a signal-conditional edge")
    print("=" * 74)
    print("  Bernoulli FLOOR. True requirement is higher: payoff dispersion,")
    print("  serially dependent fires (median defensive span 4 months), and an")
    print("  estimated rather than known blind arm all inflate it.\n")
    for rung in ("-5%", "-10%", "-15%"):
        table(rung)
    print("=" * 74)
    p0 = BLIND_RATES["-10%"]
    n50 = required_n(p0, p0 * 1.5)
    print(f"  Reference point: at the primary rung (-10%), detecting even a 50%")
    print(f"  relative lift ({p0:.1%} -> {p0*1.5:.1%}) needs {n50:.0f} fires — "
          f"{n50/4:.0f} years at 4 fires/yr.")
    print(f"  Journal-era fires available today: 0.")
    print("=" * 74)


if __name__ == "__main__":
    main()
