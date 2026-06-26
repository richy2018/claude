"""Streaming (pandas-free) backfill parser tests.

Proves the CSV-streaming path produces the SAME validated numbers as the pandas
path (NQ 2026-06-16 legacy nets -8,908 / +4,087 / +4,821) and that its import
chain pulls in NO pandas — which is what lets it run in ~35 MB alongside the
live dashboard.
"""

import csv
import io
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from backend.cot import streaming

CSV = Path(__file__).resolve().parent.parent / "backend" / "data" / "cot_nq_processed.csv"
NQ = "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE"


def _legacy_csv_text():
    ref = pd.read_csv(CSV, parse_dates=["date"])
    header = [
        "Market and Exchange Names", "As of Date in Form YYYY-MM-DD", "Open Interest (All)",
        "Noncommercial Positions-Long (All)", "Noncommercial Positions-Short (All)",
        "Commercial Positions-Long (All)", "Commercial Positions-Short (All)",
        "Nonreportable Positions-Long (All)", "Nonreportable Positions-Short (All)",
        "Change in Noncommercial-Long (All)", "% of OI-Noncommercial-Long (All)",  # decoys
    ]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for _, r in ref.iterrows():
        nc, cm, nr = int(r["noncomm_net"]), int(r["comm_net"]), int(r["nonrept_net"])
        w.writerow([
            NQ, r["date"].strftime("%Y-%m-%d"), 250000,
            max(nc, 0) + 1000, max(-nc, 0) + 1000,
            max(cm, 0) + 2000, max(-cm, 0) + 2000,
            max(nr, 0) + 500, max(-nr, 0) + 500,
            0, 5.0,
        ])
    # a row for a DIFFERENT contract, to confirm filtering keeps only NQ
    w.writerow(["GOLD - COMMODITY EXCHANGE INC.", "2026-06-16", 1, 1, 1, 1, 1, 1, 1, 0, 0])
    return buf.getvalue()


def _parse():
    reader = csv.reader(io.StringIO(_legacy_csv_text()))
    header = next(reader)
    return list(streaming.iter_parsed_rows(header, reader, "legacy_fut", {NQ: "NQ"}))


def test_streaming_legacy_ties_out():
    rows = _parse()
    last = {r["cohort"]: r for r in rows if r["report_date"].isoformat() == "2026-06-16"}
    assert last["non_comm"]["net"] == -8908
    assert last["commercial"]["net"] == 4087
    assert last["non_rept"]["net"] == 4821
    # verbatim source name preserved
    assert last["non_comm"]["contract_name"] == NQ


def test_streaming_filters_to_target_contract():
    rows = _parse()
    assert {r["symbol"] for r in rows} == {"NQ"}          # GOLD row dropped
    assert {r["cohort"] for r in rows} == {"non_comm", "commercial", "non_rept"}


def test_streaming_sum_to_zero():
    rows = _parse()
    by_date = {}
    for r in rows:
        by_date.setdefault(r["report_date"], {})[r["cohort"]] = r["net"]
    for d, c in by_date.items():
        assert c["non_comm"] + c["commercial"] + c["non_rept"] == 0, d


def test_streaming_import_chain_is_pandas_free():
    """The backfill process must not import pandas — that's what keeps it ~35 MB."""
    code = (
        "import sys; "
        "import backend.cot.streaming, backend.cot.columns, backend.cot.db, backend.cot.alerts, backend.cot.config; "
        "assert 'pandas' not in sys.modules, sorted(m for m in sys.modules if 'pandas' in m); "
        "print('pandas-free OK')"
    )
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "pandas-free OK" in out.stdout
