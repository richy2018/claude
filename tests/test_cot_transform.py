"""Validate the COT transform against the reference NQ output.

cot_nq_processed.csv is the author's validated NQ legacy output (nets + COT
index). The 2026-06-16 nets must tie out exactly:
    Non-Comm -8,908 / Comm +4,087 / Non-Rept +4,821 (ties to CFTC COT<GO>).
And our cot_index() must reproduce the CSV's noncomm_idx/comm_idx/nonrept_idx
columns to within rounding — proving the 156-week stochastic is implemented
exactly as specified (§4), not reinvented.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.cot.transform import net_position, cot_index

CSV = Path(__file__).resolve().parent.parent / "backend" / "data" / "cot_nq_processed.csv"


@pytest.fixture(scope="module")
def ref():
    return pd.read_csv(CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)


def test_net_position_helper():
    assert net_position(100, 60) == 40
    assert net_position(pd.Series([10, 20]), pd.Series([3, 25])).tolist() == [7, -5]


def test_2026_06_16_nets_tie_out(ref):
    row = ref[ref["date"] == "2026-06-16"]
    assert not row.empty, "2026-06-16 missing from reference CSV"
    assert int(row["noncomm_net"].iloc[0]) == -8908
    assert int(row["comm_net"].iloc[0]) == 4087
    assert int(row["nonrept_net"].iloc[0]) == 4821


def test_legacy_sum_to_zero(ref):
    s = ref["noncomm_net"] + ref["comm_net"] + ref["nonrept_net"]
    assert (s.abs() == 0).all(), f"{(s != 0).sum()} weeks fail sum-to-zero"


@pytest.mark.parametrize("net_col,idx_col", [
    ("noncomm_net", "noncomm_idx"),
    ("comm_net", "comm_idx"),
    ("nonrept_net", "nonrept_idx"),
])
def test_cot_index_reproduces_reference(ref, net_col, idx_col):
    computed = cot_index(ref[net_col].astype(float), lookback=156)
    expected = ref[idx_col]
    both = expected.notna() & computed.notna()
    assert both.sum() > 100, "too few overlapping points to validate"
    diff = (computed[both] - expected[both]).abs()
    assert diff.max() < 1e-6, f"{idx_col}: max diff {diff.max()} (mean {diff.mean()})"


def test_cot_index_warmup_is_null(ref):
    computed = cot_index(ref["noncomm_net"].astype(float), lookback=156)
    # min_periods = 78 -> first 77 rows must be NaN (half-formed signal hidden)
    assert computed.iloc[:77].isna().all()
    assert not np.isnan(computed.iloc[120])


def test_cot_index_bounds(ref):
    computed = cot_index(ref["noncomm_net"].astype(float), lookback=156).dropna()
    assert computed.min() >= -1e-9 and computed.max() <= 100 + 1e-9
