"""Append-only journal of GLI signals as they actually fired.

THE PROBLEM THIS SOLVES
The chart's red/green triangles are recomputed from ratio_series on every
refresh. ratio_series is built from current-vintage data, so when BIS restates a
quarter or M2's seasonal factors are re-estimated, the composite for a month two
years ago changes, its expanding-window quintile can cross a boundary, and a
triangle silently appears, moves, or vanishes. The chart then shows a history
that nobody could have traded.

Recomputing cannot fix this — revisions are real and the old values are gone.
The only way a triangle can be trusted is if it was WRITTEN DOWN when it fired
and never touched again. That is what this module does.

WHAT IS AND IS NOT RECOVERABLE
Everything recorded from the moment this ships is genuine: observed values, as
they stood, at the date they were seen. Everything before it is a reconstruction
and is marked as such, permanently. There is no way to recover what the signal
would have said in 2011 — that information was overwritten by later revisions
long ago. Do not let a chart imply otherwise.

DRIFT TRACKING
On every refresh the journal also recomputes what each past month WOULD say on
today's data and stores the difference. That costs nothing and directly measures
how much revisions move the signal — the question this whole exercise started
from. See `drift_report()`.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_RENDER_DISK = Path("/opt/render/data")
JOURNAL_PATH = ((_RENDER_DISK if _RENDER_DISK.exists()
                 else Path(__file__).resolve().parent) / "signal_journal.json")

SCHEMA_VERSION = 1


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _load_raw():
    if not JOURNAL_PATH.exists():
        return {"schema": SCHEMA_VERSION, "models": {}}
    try:
        data = json.loads(JOURNAL_PATH.read_text())
        data.setdefault("models", {})
        return data
    except Exception as e:                                   # noqa: BLE001
        print(f"[JOURNAL] Unreadable at {JOURNAL_PATH} ({e}) — starting a new one. "
              f"The existing file is NOT overwritten until a successful write.")
        return {"schema": SCHEMA_VERSION, "models": {}}


def _save_raw(data):
    try:
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = JOURNAL_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(JOURNAL_PATH)                            # atomic
        return True
    except Exception as e:                                   # noqa: BLE001
        print(f"[JOURNAL] SAVE FAILED: {e}")
        return False


def record_reading(model, signal_month, quintile, composite=None,
                   components=None, source_dates=None, lags_applied=None,
                   filtered_quintile=None, filter_triggered=None):
    """Record one month's signal. First write wins — never overwritten.

    Args:
        model: e.g. "5f".
        signal_month: "YYYY-MM-01", the month the reading refers to.
        quintile: raw momentum quintile 1-5.
        composite: composite value behind it.
        components: {key: value} as used at record time.
        source_dates: {key: "YYYY-MM-DD"} last real observation per factor —
            the closest thing to a vintage stamp available without ALFRED.
        lags_applied: {key: months} publication lags in force.
        filtered_quintile / filter_triggered: Rule A outcome, if applied.

    Returns:
        dict with `status` one of "recorded", "already_present", "drift_logged".
    """
    data = _load_raw()
    model_entries = data["models"].setdefault(model, {})
    key = str(signal_month)[:10]

    candidate = {
        "signal_month": key,
        "quintile": None if quintile is None else int(quintile),
        "filtered_quintile": (None if filtered_quintile is None
                              else int(filtered_quintile)),
        "filter_triggered": bool(filter_triggered) if filter_triggered is not None else None,
        "composite": None if composite is None else round(float(composite), 6),
        "components": components or {},
        "source_dates": source_dates or {},
        "lags_applied": lags_applied or {},
        "recorded_at": _utcnow(),
        "recorded_live": True,
    }

    existing = model_entries.get(key)
    if existing is None:
        model_entries[key] = candidate
        _save_raw(data)
        print(f"[JOURNAL] Recorded {model} {key}: Q{candidate['quintile']} "
              f"(first observation — this is now immutable)")
        return {"status": "recorded", "entry": candidate}

    # Already recorded. Do NOT overwrite — but note whether today's data would
    # now produce something different. That difference IS the revision effect.
    drift = None
    if (existing.get("quintile") != candidate["quintile"]
            or (existing.get("composite") is not None
                and candidate["composite"] is not None
                and abs(existing["composite"] - candidate["composite"]) > 1e-9)):
        drift = {
            "observed_at": _utcnow(),
            "quintile_now": candidate["quintile"],
            "composite_now": candidate["composite"],
        }
        history = existing.setdefault("drift", [])
        # Keep the record compact: only log a genuinely new divergence.
        if not history or history[-1].get("quintile_now") != drift["quintile_now"] \
                or history[-1].get("composite_now") != drift["composite_now"]:
            history.append(drift)
            _save_raw(data)
            moved = existing.get("quintile") != candidate["quintile"]
            print(f"[JOURNAL] DRIFT on {model} {key}: recorded Q{existing.get('quintile')}"
                  f" -> today's data says Q{candidate['quintile']}"
                  + ("  *** QUINTILE CHANGED — a past triangle would have moved ***"
                     if moved else " (composite only)"))
            return {"status": "drift_logged", "entry": existing, "drift": drift}

    return {"status": "already_present", "entry": existing}


def record_many(model, readings):
    """Record a batch in ONE load/save cycle.

    record_reading() reads and writes the whole file per call, which is fine for
    a single month but not for re-offering a few hundred chart points on every
    refresh — that would be hundreds of round-trips to a network disk. Same
    semantics as record_reading: first write per month wins, disagreements are
    logged as drift.

    Args:
        model: e.g. "5f".
        readings: iterable of dicts with at least signal_month and quintile;
            composite, components, source_dates, lags_applied,
            filtered_quintile and filter_triggered are optional.

    Returns:
        {"recorded": n, "already_present": n, "drift_logged": n}
    """
    data = _load_raw()
    model_entries = data["models"].setdefault(model, {})
    counts = {"recorded": 0, "already_present": 0, "drift_logged": 0}
    dirty = False
    moved_months = []

    for r in readings:
        key = str(r.get("signal_month", ""))[:10]
        if not key:
            continue
        q = r.get("quintile")
        comp = r.get("composite")
        candidate = {
            "signal_month": key,
            "quintile": None if q is None else int(q),
            "filtered_quintile": (None if r.get("filtered_quintile") is None
                                  else int(r["filtered_quintile"])),
            "filter_triggered": (None if r.get("filter_triggered") is None
                                 else bool(r["filter_triggered"])),
            "composite": None if comp is None else round(float(comp), 6),
            "components": r.get("components") or {},
            "source_dates": r.get("source_dates") or {},
            "lags_applied": r.get("lags_applied") or {},
            "recorded_at": _utcnow(),
            "recorded_live": True,
        }

        existing = model_entries.get(key)
        if existing is None:
            model_entries[key] = candidate
            counts["recorded"] += 1
            dirty = True
            continue

        q_changed = existing.get("quintile") != candidate["quintile"]
        c_changed = (existing.get("composite") is not None
                     and candidate["composite"] is not None
                     and abs(existing["composite"] - candidate["composite"]) > 1e-9)
        if not (q_changed or c_changed):
            counts["already_present"] += 1
            continue

        history = existing.setdefault("drift", [])
        entry = {"observed_at": candidate["recorded_at"],
                 "quintile_now": candidate["quintile"],
                 "composite_now": candidate["composite"]}
        if (not history
                or history[-1].get("quintile_now") != entry["quintile_now"]
                or history[-1].get("composite_now") != entry["composite_now"]):
            history.append(entry)
            counts["drift_logged"] += 1
            dirty = True
            if q_changed:
                moved_months.append((key, existing.get("quintile"), candidate["quintile"]))
        else:
            counts["already_present"] += 1

    if dirty:
        _save_raw(data)

    if counts["recorded"]:
        print(f"[JOURNAL] {model}: recorded {counts['recorded']} new month(s)")
    if moved_months:
        print(f"[JOURNAL] {model}: {len(moved_months)} recorded month(s) would fire a "
              f"DIFFERENT quintile on today's data — past triangles would have moved:")
        for k, was, now in moved_months[:10]:
            print(f"[JOURNAL]     {k}: fired Q{was} -> today Q{now}")
        if len(moved_months) > 10:
            print(f"[JOURNAL]     ... and {len(moved_months) - 10} more")

    return counts


def load_journal(model):
    """All recorded entries for a model, oldest first."""
    data = _load_raw()
    entries = data["models"].get(model, {})
    return [entries[k] for k in sorted(entries)]


def journal_months(model):
    """Set of months already recorded — cheap membership test."""
    return set(_load_raw()["models"].get(model, {}))


def drift_report(model):
    """How much have revisions moved already-fired signals?

    This is the live-signal counterpart to the backtest audit: it answers
    "would the triangles on my chart have been different?" with observed
    evidence rather than simulation.
    """
    entries = load_journal(model)
    with_drift = [e for e in entries if e.get("drift")]
    quintile_moves = [
        e for e in with_drift
        if any(d.get("quintile_now") != e.get("quintile") for d in e["drift"])
    ]
    return {
        "model": model,
        "months_recorded": len(entries),
        "months_with_any_drift": len(with_drift),
        "months_where_quintile_changed": len(quintile_moves),
        "quintile_change_rate_pct": (round(len(quintile_moves) / len(entries) * 100, 1)
                                     if entries else None),
        "first_recorded": entries[0]["signal_month"] if entries else None,
        "last_recorded": entries[-1]["signal_month"] if entries else None,
        "changed_months": [
            {"signal_month": e["signal_month"],
             "recorded_quintile": e["quintile"],
             "latest_quintile": e["drift"][-1]["quintile_now"]}
            for e in quintile_moves
        ],
        "note": (
            "Months recorded before this journal existed are reconstructions "
            "and are absent here. Only months present below are known to be "
            "what the signal actually said at the time."
        ),
    }


def annotate_series(model, points, date_key="date", quintile_key="quintile"):
    """Tag chart points as live-recorded or reconstructed.

    Lets the UI draw a triangle that was genuinely fired differently from one
    inferred after the fact, instead of presenting both as equally real.
    """
    recorded = {e["signal_month"]: e for e in load_journal(model)}
    out = []
    for p in points:
        d = str(p.get(date_key, ""))[:10]
        entry = recorded.get(d)
        q = p.get(quintile_key)
        item = dict(p)
        item["recorded_live"] = entry is not None
        if entry is not None:
            item["quintile_as_fired"] = entry.get("quintile")
            item["quintile_moved_since"] = (
                entry.get("quintile") is not None and q is not None
                and int(entry["quintile"]) != int(q)
            )
        out.append(item)
    return out
