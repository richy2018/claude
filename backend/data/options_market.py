"""NDX, VIX and SKEW history from backend/data/for options.csv.

Bloomberg export, three side-by-side date/value blocks in one sheet:

    DATE;NDX;;DATE;VIX;;DATE;SKEW
    02.01.1990;227.73;;02.01.1990;17.24;;02.01.1990;126.09

European dates, semicolon-delimited, blank spacer columns between blocks, and
each block carries its own date column because the three series have slightly
different holiday calendars — they are NOT row-aligned and must not be zipped
together positionally.

History runs from 1990-01, which is what makes it useful here: it spans
dot-com, the GFC and COVID, so drawdown base rates are measured across three
genuinely different crisis regimes rather than one.

None of these three are ever restated — index levels and CBOE index values are
published and final. So anything computed from this file is point-in-time by
construction, with no vintage reconstruction required.
"""

from pathlib import Path

import pandas as pd

DEFAULT_PATH = Path(__file__).resolve().parent / "for options.csv"

# (date column, value column) per block, as pandas names them after the
# duplicate-header rename.
_BLOCKS = [("DATE", "NDX"), ("DATE.1", "VIX"), ("DATE.2", "SKEW")]


def load_options_market(path=None, strict=False):
    """Load the export into {"NDX": Series, "VIX": Series, "SKEW": Series}.

    Each series is independently indexed and sorted, deduplicated keeping the
    last observation. Missing file returns {} unless strict.
    """
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        if strict:
            raise FileNotFoundError(f"options market export not found at {p}")
        print(f"[OPTMKT] No export at {p}")
        return {}

    df = pd.read_csv(p, sep=";", dtype=str)
    out = {}
    for dcol, vcol in _BLOCKS:
        if dcol not in df.columns or vcol not in df.columns:
            continue
        dates = pd.to_datetime(df[dcol], format="%d.%m.%Y", errors="coerce")
        vals = pd.to_numeric(df[vcol].str.replace(",", ".", regex=False),
                             errors="coerce")
        s = pd.Series(vals.to_numpy(), index=dates).dropna().sort_index()
        s = s[~s.index.duplicated(keep="last")]
        s.name = vcol
        out[vcol] = s
        print(f"[OPTMKT] {vcol:<5} {len(s):>5} obs  "
              f"{s.index[0]:%Y-%m-%d} -> {s.index[-1]:%Y-%m-%d}")
    return out
