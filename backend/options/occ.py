"""Parse OCC option symbols from the OPRA flat files.

Flat-file day-aggregate rows are keyed by OCC symbol, e.g.
`O:SPXW260724C02600000` = root SPXW, expiry 2026-07-24, call, strike 2600.000.
Layout after the `O:` prefix: <root><YYMMDD><C|P><strike*1000, 8 digits>.

The root matters: `O:SPX...` is a prefix shared by SPX index options (roots
SPX, SPXW) AND unrelated names like SPXL (a leveraged ETF). We parse the exact
root and match it, never a bare prefix, so ETF options never leak into the SPX
index reconstruction.
"""

import datetime as dt

# SPX *index* option roots. SPX = AM-settled monthlies; SPXW = PM-settled
# weeklies/dailies. Both are the S&P 500 index — SPXL/SPXS/etc. are not.
SPX_ROOTS = ("SPX", "SPXW")

_TAIL = 15  # YYMMDD(6) + C/P(1) + strike(8)


def parse_occ_ticker(ticker: str):
    """{root, expiry, ctype, strike} or None if the symbol isn't a valid OCC
    option (index/equity option, not a future or the underlying itself)."""
    if not ticker or not ticker.startswith("O:"):
        return None
    body = ticker[2:]
    if len(body) <= _TAIL:                 # need at least one root char + tail
        return None
    root, tail = body[:-_TAIL], body[-_TAIL:]
    ymd, cp, strike_raw = tail[:6], tail[6], tail[7:]
    if cp not in ("C", "P") or not ymd.isdigit() or not strike_raw.isdigit():
        return None
    try:
        expiry = dt.date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6])).isoformat()
    except ValueError:
        return None
    return {"root": root, "expiry": expiry,
            "ctype": "call" if cp == "C" else "put",
            "strike": int(strike_raw) / 1000.0}


def is_spx_index(ticker: str) -> bool:
    p = parse_occ_ticker(ticker)
    return bool(p and p["root"] in SPX_ROOTS)
