"""Options module configuration. All thresholds live here, not scattered."""

import os
from pathlib import Path

# ── API ──────────────────────────────────────────────────────────────────────
MASSIVE_BASE_URL = "https://api.massive.com"
UNDERLYING = "I:SPX"          # index options use the I: prefix
API_KEY_ENV = "MASSIVE_API_KEY"   # key comes ONLY from the environment


def api_key():
    return os.environ.get(API_KEY_ENV, "")


# ── Storage (Render persistent disk when present, local data dir otherwise) ──
def _data_dir() -> Path:
    render_disk = Path("/opt/render/data")
    base = render_disk if render_disk.exists() else Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return _data_dir() / "options_history.db"


# Capability report written by scripts/probe_massive.py. Gates every feature.
CAPABILITIES_PATH = Path(__file__).resolve().parent.parent / "data" / "massive_capabilities.json"

# ── Hygiene filters (applied before ANY aggregate; exclusions are reported) ──
BAND_PCT = 0.20               # keep strikes within ±20% of spot
STALE_VOL_OI = 0.10           # volume/OI below this flags a strike stale/legacy

# ── Expiry buckets (calendar days to expiry) ─────────────────────────────────
BUCKETS = (("0-7d", 0, 7), ("8-30d", 8, 30), ("31d+", 31, 100000))

# ── Dealer-gamma model constants ─────────────────────────────────────────────
RISK_FREE = 0.04              # r
DIV_YIELD = 0.015             # q
SWEEP_LO, SWEEP_HI, SWEEP_STEP = -0.15, 0.15, 0.005   # spot sweep −15%..+15%, 0.5% steps
A_SCENARIOS = (1.00, 0.75, 0.50, 0.25)                # dealer-long-call share
CONTRACT_MULT = 100

# The inventory assumption, stated verbatim in the UI panel (spec requirement).
GAMMA_ASSUMPTION_TEXT = (
    "Dealers assumed long call OI, short put OI. Assumption, not observation."
)

# ── History / percentile rules ───────────────────────────────────────────────
PERCENTILE_MIN_SESSIONS = 60  # percentiles show PENDING until this many sessions
RV_WINDOWS = (10, 20, 30)     # realised-vol windows (sessions, close-to-close)

# ── Scheduler ────────────────────────────────────────────────────────────────
# Daily snapshot after US close. 19:30 UTC = 22:30 Riga in summer (EEST);
# override with OPTIONS_SNAPSHOT_UTC="HH:MM". Disable with OPTIONS_SCHEDULER=off.
SNAPSHOT_UTC_DEFAULT = "19:30"


def snapshot_utc() -> str:
    return os.environ.get("OPTIONS_SNAPSHOT_UTC", SNAPSHOT_UTC_DEFAULT)


def scheduler_enabled() -> bool:
    return os.environ.get("OPTIONS_SCHEDULER", "on").lower() not in ("off", "0", "false")
