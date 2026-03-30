"""SOFR curve parsing and STIR (Short-Term Interest Rate) calculations."""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path


# FOMC meeting dates for 2025-2027 (approximate schedule)
FOMC_MEETINGS = [
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
    # 2027
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-15",
]

# SOFR futures contract codes by month
FUTURES_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}


def parse_sofr_csv(filepath: str) -> pd.DataFrame:
    """
    Parse Bloomberg SOFR curve CSV/Excel export.
    Expected columns: Term, Unit, Bid, Ask, Final Bid Rate, Final Ask Rate, Daycount
    """
    path = Path(filepath)
    if path.suffix in (".xlsx", ".xls"):
        df = pd.read_excel(filepath)
    else:
        df = pd.read_csv(filepath)

    # Normalize column names
    df.columns = [c.strip() for c in df.columns]

    # Compute mid rate
    bid_col = "Final Bid Rate" if "Final Bid Rate" in df.columns else "Bid"
    ask_col = "Final Ask Rate" if "Final Ask Rate" in df.columns else "Ask"

    df["mid"] = (df[bid_col] + df[ask_col]) / 2

    # Parse term into months
    df["term_months"] = df.apply(_parse_term_to_months, axis=1)
    df = df.sort_values("term_months")

    return df


def _parse_term_to_months(row) -> float:
    """Convert term/unit to months."""
    term = row["Term"]
    unit = str(row["Unit"]).strip().upper()

    if unit == "WK":
        return term / 4.33
    elif unit == "MO":
        return term
    elif unit == "YR":
        return term * 12
    else:
        return term


def generate_sample_sofr_curve(current_ffr: float = 3.625) -> pd.DataFrame:
    """Generate a realistic sample SOFR curve for development/demo purposes."""
    terms = [
        (1, "WK"), (2, "WK"), (3, "WK"),
        (1, "MO"), (2, "MO"), (3, "MO"), (4, "MO"), (5, "MO"),
        (6, "MO"), (7, "MO"), (8, "MO"), (9, "MO"), (10, "MO"),
        (11, "MO"), (12, "MO"), (18, "MO"),
        (1, "YR"), (2, "YR"), (3, "YR"), (4, "YR"), (5, "YR"),
        (6, "YR"), (7, "YR"), (8, "YR"), (9, "YR"), (10, "YR"),
        (12, "YR"), (15, "YR"), (20, "YR"), (25, "YR"), (30, "YR"),
        (40, "YR"), (50, "YR"),
    ]

    rows = []
    for term_val, unit in terms:
        if unit == "WK":
            months = term_val / 4.33
        elif unit == "MO":
            months = term_val
        else:
            months = term_val * 12

        # Generate a realistic inverted-then-normalizing curve
        if months <= 1:
            rate = current_ffr + 0.03
        elif months <= 3:
            rate = current_ffr + 0.01 - months * 0.005
        elif months <= 6:
            rate = current_ffr - 0.02 - (months - 3) * 0.015
        elif months <= 12:
            rate = current_ffr - 0.07 - (months - 6) * 0.012
        elif months <= 24:
            rate = current_ffr - 0.15 - (months - 12) * 0.005
        elif months <= 60:
            rate = current_ffr - 0.20 + (months - 24) * 0.002
        elif months <= 120:
            rate = current_ffr - 0.12 + (months - 60) * 0.003
        else:
            rate = current_ffr - 0.05 + (months - 120) * 0.0005

        # Add some noise
        spread = 0.003
        bid = rate - spread
        ask = rate + spread
        mid = rate

        rows.append({
            "Term": term_val,
            "Unit": unit,
            "Bid": round(bid, 9),
            "Ask": round(ask, 9),
            "Final Bid Rate": round(bid, 9),
            "Final Ask Rate": round(ask, 9),
            "Daycount": "ACT/360",
            "mid": round(mid, 9),
            "term_months": round(months, 2),
        })

    return pd.DataFrame(rows)


def compute_implied_fed_funds_path(sofr_df: pd.DataFrame, current_ffr: float = 3.625) -> list:
    """
    Build the staircase implied Fed Funds path from the SOFR curve.
    Returns list of steps: { date, rate, meeting_label }
    """
    today = datetime.now()

    # Get rates at monthly intervals from the curve
    monthly_rates = []
    for _, row in sofr_df.iterrows():
        months = row["term_months"]
        if 0 < months <= 30:  # Only front 30 months
            target_date = today + timedelta(days=months * 30.44)
            monthly_rates.append({
                "months": months,
                "date": target_date.strftime("%Y-%m-%d"),
                "rate": row["mid"],
            })

    if not monthly_rates:
        return []

    # Build staircase: rates stay flat between meetings, step at each meeting
    path = []
    meetings = [datetime.strptime(m, "%Y-%m-%d") for m in FOMC_MEETINGS if datetime.strptime(m, "%Y-%m-%d") > today]

    # Start with current FFR
    path.append({
        "date": today.strftime("%Y-%m-%d"),
        "rate": current_ffr,
        "label": "Current",
    })

    # For each meeting, interpolate the implied rate from the curve
    for meeting_date in meetings[:12]:  # Next 12 meetings
        months_fwd = (meeting_date - today).days / 30.44
        # Find the two nearest curve points and interpolate
        rate = _interpolate_rate(sofr_df, months_fwd)
        if rate is not None:
            path.append({
                "date": meeting_date.strftime("%Y-%m-%d"),
                "rate": round(rate, 3),
                "label": meeting_date.strftime("%b %y"),
            })

    return path


def _interpolate_rate(sofr_df: pd.DataFrame, target_months: float) -> float:
    """Interpolate a rate from the SOFR curve at a given forward month."""
    df = sofr_df.sort_values("term_months")
    if target_months <= df["term_months"].iloc[0]:
        return float(df["mid"].iloc[0])
    if target_months >= df["term_months"].iloc[-1]:
        return float(df["mid"].iloc[-1])

    # Find bracketing points
    below = df[df["term_months"] <= target_months].iloc[-1]
    above = df[df["term_months"] > target_months].iloc[0]

    # Linear interpolation
    frac = (target_months - below["term_months"]) / (above["term_months"] - below["term_months"])
    return float(below["mid"] + frac * (above["mid"] - below["mid"]))


def compute_meeting_probabilities(sofr_df: pd.DataFrame, current_ffr: float = 3.625) -> list:
    """
    Compute probability of rate changes at each FOMC meeting.
    Uses the spread between adjacent forward rates to derive cut/hike probabilities.
    """
    today = datetime.now()
    meetings = [datetime.strptime(m, "%Y-%m-%d") for m in FOMC_MEETINGS if datetime.strptime(m, "%Y-%m-%d") > today]

    if not meetings:
        return []

    results = []
    prev_rate = current_ffr

    for i, meeting_date in enumerate(meetings[:12]):
        months_fwd = (meeting_date - today).days / 30.44
        implied_rate = _interpolate_rate(sofr_df, months_fwd)
        if implied_rate is None:
            continue

        # Post-meeting implied rate (next meeting or slightly after this one)
        post_months = months_fwd + 0.5
        post_rate = _interpolate_rate(sofr_df, post_months)
        if post_rate is None:
            post_rate = implied_rate

        # Expected change at this meeting = difference between post-meeting and pre-meeting implied rate
        meeting_chg_bp = (post_rate - implied_rate) * 100  # bp change at this meeting

        # Derive probabilities assuming 25bp increments
        # Negative meeting_chg_bp = rate cut priced in; positive = rate hike or hold
        cuts_frac = meeting_chg_bp / -25.0  # fractional 25bp cuts (negative = hike)

        if cuts_frac >= 0:
            # Market pricing cuts or hold
            p_hold = max(0, 1 - cuts_frac)
            p_25 = min(1, cuts_frac)
            p_50 = max(0, min(1, cuts_frac - 1))
            p_75 = max(0, min(1, cuts_frac - 2))
        else:
            # Market pricing hike or hold (cuts_frac < 0)
            p_hold = max(0, 1 + cuts_frac)  # e.g., cuts_frac=-0.3 -> 70% hold
            p_25 = 0
            p_50 = 0
            p_75 = 0

        # Normalize
        total = p_hold + p_25 + p_50 + p_75
        if total > 0:
            p_hold /= total
            p_25 /= total
            p_50 /= total
            p_75 /= total

        # Cumulative cuts from current FFR
        cum_cuts = (current_ffr - post_rate) / 0.25

        # Futures contract code
        year_digit = meeting_date.year % 10
        month_code = FUTURES_MONTH_CODES.get(meeting_date.month, "?")
        contract = f"FF{month_code}{year_digit}"

        results.append({
            "date": meeting_date.strftime("%Y-%m-%d"),
            "date_label": meeting_date.strftime("%b %d"),
            "contract": contract,
            "rate": round(implied_rate, 3),
            "post_mtg": round(post_rate, 3),
            "hold": round(p_hold * 100, 0),
            "cut_25": round(p_25 * 100, 0),
            "cut_50": round(p_50 * 100, 0),
            "cut_75": round(p_75 * 100, 0),
            "cum_cuts": round(cum_cuts, 1),
        })

        prev_rate = post_rate

    return results


def compute_terminal_rate(sofr_df: pd.DataFrame) -> dict:
    """Compute terminal rate (lowest forward rate) and related metrics."""
    if sofr_df.empty:
        return {"terminal": 0, "terminal_contract": "", "frnt_term": 0, "term_6m": 0, "term_12m": 0}

    # Look for the terminal rate = minimum in the 6M-48M window (where the curve troughs)
    front = sofr_df[(sofr_df["term_months"] >= 6) & (sofr_df["term_months"] <= 48)].copy()
    if front.empty:
        front = sofr_df[sofr_df["term_months"] <= 48].copy()
    if front.empty:
        return {"terminal": 0, "terminal_contract": "", "frnt_term": 0, "term_6m": 0, "term_12m": 0}

    # Terminal = minimum implied rate in the search window
    min_idx = front["mid"].idxmin()
    terminal_row = front.loc[min_idx]
    terminal_rate = float(terminal_row["mid"])
    terminal_months = float(terminal_row["term_months"])

    # Front rate (1-3 month average)
    short_front = sofr_df[sofr_df["term_months"] <= 3]["mid"]
    front_rate = float(short_front.mean()) if len(short_front) > 0 else terminal_rate

    # Rate at terminal+6M and terminal+12M forward
    rate_6m = _interpolate_rate(sofr_df, terminal_months + 6)
    # Rate at terminal+12M forward
    rate_12m = _interpolate_rate(sofr_df, terminal_months + 12)

    # Terminal contract label
    today = datetime.now()
    terminal_date = today + timedelta(days=terminal_months * 30.44)
    month_code = FUTURES_MONTH_CODES.get(terminal_date.month, "?")
    year_digit = terminal_date.year % 10
    terminal_contract = f"SFR{month_code}{year_digit} M+{int(terminal_months)}"

    return {
        "terminal": round(terminal_rate, 3),
        "terminal_pct": f"{terminal_rate:.3f}%",
        "terminal_contract": terminal_contract,
        "front_rate": round(front_rate, 3),
        "frnt_term": round((front_rate - terminal_rate) * 100, 1),  # bp
        "term_6m": round((terminal_rate - (rate_6m or terminal_rate)) * 100, 1) if rate_6m else 0,
        "term_12m": round((terminal_rate - (rate_12m or terminal_rate)) * 100, 1) if rate_12m else 0,
    }


def get_sofr_strip(sofr_df: pd.DataFrame, view: str = "mid") -> list:
    """Get the SOFR strip as a table for display."""
    rows = []
    for _, r in sofr_df.iterrows():
        unit = str(r["Unit"]).strip().upper()
        label = f"{int(r['Term'])} {unit}"
        row = {
            "label": label,
            "term": int(r["Term"]),
            "unit": unit,
            "term_months": round(r["term_months"], 2),
            "bid": round(float(r.get("Bid", r.get("Final Bid Rate", 0))), 6),
            "ask": round(float(r.get("Ask", r.get("Final Ask Rate", 0))), 6),
            "mid": round(float(r["mid"]), 6),
            "daycount": r.get("Daycount", "ACT/360"),
        }
        rows.append(row)
    return rows


def compute_key_spreads(sofr_df: pd.DataFrame) -> list:
    """Compute key rate spreads from the SOFR curve."""
    spreads = []

    def _get_rate(months):
        return _interpolate_rate(sofr_df, months)

    pairs = [
        ("1M-3M", 1, 3),
        ("3M-6M", 3, 6),
        ("6M-12M", 6, 12),
        ("1Y-2Y", 12, 24),
        ("2Y-5Y", 24, 60),
        ("5Y-10Y", 60, 120),
        ("2Y-10Y", 24, 120),
        ("5Y-30Y", 60, 360),
        ("Front-Back", 1, 24),
    ]

    for label, m1, m2 in pairs:
        r1 = _get_rate(m1)
        r2 = _get_rate(m2)
        if r1 is not None and r2 is not None:
            spread = (r2 - r1) * 100  # bp
            spreads.append({
                "label": label,
                "short_tenor": m1,
                "long_tenor": m2,
                "short_rate": round(r1, 4),
                "long_rate": round(r2, 4),
                "spread_bp": round(spread, 1),
            })

    return spreads
