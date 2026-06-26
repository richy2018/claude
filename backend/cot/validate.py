"""Validation / integrity gates (§5) — build in, fail loud.

Each gate routes failures to alerts.emit_alert / record_validation so silent
staleness or a CFTC format change surfaces on /api/cot/health instead of
quietly serving bad positioning.
"""

from datetime import date, datetime, timedelta

import pandas as pd

from . import alerts


# Gate 2 tie-out anchors: latest published nets we have independently checked.
# NQ legacy 2026-06-16 ties to CFTC COT<GO> (the reference build). Extend with
# one anchor per report type as they are verified.
TIE_OUT_ANCHORS = {
    ("NQ", "legacy_fut", "2026-06-16"): {
        "non_comm": -8908, "commercial": 4087, "non_rept": 4821,
    },
}


def check_sum_to_zero(rows: list[dict], symbol: str = "") -> bool:
    """Gate 1: legacy non_comm + commercial + non_rept net == 0 every week.
    Free per-row integrity test — any non-zero means a parse/cohort error."""
    legacy = [r for r in rows if r["report_type"] == "legacy_fut"]
    if not legacy:
        return True
    df = pd.DataFrame(legacy)
    piv = df.pivot_table(index="report_date", columns="cohort", values="net", aggfunc="last")
    needed = {"non_comm", "commercial", "non_rept"}
    if not needed.issubset(piv.columns):
        return alerts.record_validation(
            "sum_to_zero", False,
            f"{symbol}: legacy missing cohorts {needed - set(piv.columns)}")
    sums = piv[["non_comm", "commercial", "non_rept"]].sum(axis=1)
    bad = sums[sums.abs() > 0].dropna()
    if len(bad) > 0:
        worst = bad.abs().max()
        return alerts.record_validation(
            "sum_to_zero", False,
            f"{symbol}: {len(bad)} legacy weeks with non-zero net sum (worst {worst:.0f}), "
            f"e.g. {bad.index[-1]}={bad.iloc[-1]:.0f}")
    return alerts.record_validation("sum_to_zero", True, f"{symbol}: {len(sums)} legacy weeks balance")


def check_tie_out(rows: list[dict]) -> bool:
    """Gate 2: latest week's published nets match a stored known value."""
    ok_all = True
    by_key = {}
    for r in rows:
        by_key.setdefault((r["symbol"], r["report_type"], str(r["report_date"])), {})[r["cohort"]] = r["net"]
    for (sym, rtype, d), expected in TIE_OUT_ANCHORS.items():
        got = by_key.get((sym, rtype, d))
        if got is None:
            continue  # anchor date not in this batch — skip silently
        mism = {c: (expected[c], got.get(c)) for c in expected if got.get(c) != expected[c]}
        if mism:
            ok_all = False
            alerts.record_validation(
                "tie_out", False, f"{sym}/{rtype} {d} mismatch: {mism}")
        else:
            alerts.record_validation("tie_out", True, f"{sym}/{rtype} {d} ties out")
    return ok_all


def check_freshness(latest: date | None, as_of: date | None = None) -> bool:
    """Gate 3: if the newest report_date hasn't advanced by Saturday, alert
    (CFTC releases Fri; a stale Saturday means a missed release / format change)."""
    as_of = as_of or datetime.utcnow().date()
    if latest is None:
        return alerts.record_validation("freshness", False, "no data stored")
    # Expected newest report covers the prior Tuesday; if it's older than ~10
    # days and today is Sat+, the weekly release was missed.
    age_days = (as_of - latest).days
    is_weekend = as_of.weekday() >= 5  # Sat/Sun
    if age_days > 10 and is_weekend:
        return alerts.record_validation(
            "freshness", False, f"newest report_date {latest} is {age_days}d old on {as_of}")
    return alerts.record_validation("freshness", True, f"newest report_date {latest} ({age_days}d old)")


def warmup_ok(n_weeks: int, lookback: int = 156) -> bool:
    """Gate 4 helper: COT index is only meaningful once `lookback` history
    exists. The transform already nulls the warmup; this just records status."""
    ok = n_weeks >= lookback // 2
    alerts.record_validation(
        "cot_index_warmup", True,
        f"{n_weeks} weeks stored ({'index live' if ok else 'still warming up'}, lookback {lookback})")
    return ok


def run_all_gates(rows: list[dict], symbol: str = "", latest: date | None = None) -> dict:
    """Run every gate over a batch of rows, returning a summary dict."""
    res = {
        "sum_to_zero": check_sum_to_zero(rows, symbol),
        "tie_out": check_tie_out(rows),
        "freshness": check_freshness(latest) if latest is not None else None,
        "warmup": warmup_ok(len(set(r["report_date"] for r in rows))),
    }
    return res
