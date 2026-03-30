import { COLORS, FONT } from '../utils/theme.js';

// ---------------------------------------------------------------------------
// Helper: convert range string to approximate trading-day count
// YTD is calculated dynamically from Jan 1 of the current year.
// ALL returns 0, meaning "no limit".
// ---------------------------------------------------------------------------
export function rangeToDays(rangeStr) {
  const STATIC = {
    '1M':  21,
    '3M':  63,
    '6M':  126,
    '1Y':  252,
    '2Y':  504,
    '5Y':  1260,
    '10Y': 2520,
    '15Y': 3780,
    '20Y': 5040,
    'ALL': 0,
  };

  if (rangeStr in STATIC) return STATIC[rangeStr];

  if (rangeStr === 'YTD') {
    const now = new Date();
    const jan1 = new Date(now.getFullYear(), 0, 1);
    const calendarDays = Math.floor((now - jan1) / (1000 * 60 * 60 * 24));
    // approximate: trading days ≈ calendar days * (252/365)
    return Math.round(calendarDays * (252 / 365));
  }

  return 0;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

const styles = {
  row: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: '0',
    padding: '8px 16px',
    background: COLORS.bg,
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    fontFamily: FONT,
    fontSize: '11px',
    userSelect: 'none',
  },
  group: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  label: {
    color: COLORS.textMuted,
    marginRight: '6px',
    letterSpacing: '0.05em',
    whiteSpace: 'nowrap',
  },
  divider: {
    color: COLORS.textMuted,
    padding: '0 12px',
    fontSize: '13px',
    lineHeight: 1,
    alignSelf: 'center',
  },
};

function btnStyle(active) {
  return {
    fontFamily: FONT,
    fontSize: '11px',
    padding: '3px 7px',
    border: active ? `1px solid ${COLORS.amber}` : `1px solid #333`,
    borderRadius: '2px',
    background: active ? COLORS.amber : '#1a1a1a',
    color: active ? '#0a0a0a' : '#888',
    cursor: 'pointer',
    letterSpacing: '0.03em',
    lineHeight: '16px',
    transition: 'none',
    outline: 'none',
    whiteSpace: 'nowrap',
  };
}

function ToggleGroup({ label, options, value, onChange, formatLabel }) {
  return (
    <div style={styles.group}>
      <span style={styles.label}>{label}:</span>
      {options.map((opt) => {
        const display = formatLabel ? formatLabel(opt) : String(opt);
        const isActive = opt === value;
        return (
          <button
            key={opt}
            style={btnStyle(isActive)}
            onClick={() => !isActive && onChange(opt)}
            aria-pressed={isActive}
          >
            {display}
          </button>
        );
      })}
    </div>
  );
}

function Divider() {
  return <span style={styles.divider}>|</span>;
}

// ---------------------------------------------------------------------------
// ControlsRow
// ---------------------------------------------------------------------------

const METHOD_OPTIONS  = ['vol-scaled', 'z-score'];
const METHOD_LABELS   = { 'vol-scaled': 'VOL-SCALED', 'z-score': 'Z-SCORE' };

const LOOKBACK_OPTIONS = [5, 10, 21, 28, 63];
const VOL_OPTIONS      = [10, 21, 42, 63];
const RANGE_OPTIONS    = ['1M', '3M', '6M', 'YTD', '1Y', '2Y', '5Y', '10Y', '15Y', '20Y', 'ALL'];

export default function ControlsRow({
  method,
  lookback,
  volWindow,
  range,
  onMethodChange,
  onLookbackChange,
  onVolWindowChange,
  onRangeChange,
}) {
  return (
    <div style={styles.row}>
      {/* 1 — METHOD */}
      <ToggleGroup
        label="METHOD"
        options={METHOD_OPTIONS}
        value={method}
        onChange={onMethodChange}
        formatLabel={(opt) => METHOD_LABELS[opt]}
      />

      <Divider />

      {/* 2 — LOOKBACK */}
      <ToggleGroup
        label="LOOKBACK"
        options={LOOKBACK_OPTIONS}
        value={lookback}
        onChange={onLookbackChange}
        formatLabel={(d) => `${d}D`}
      />

      <Divider />

      {/* 3 — VOL */}
      <ToggleGroup
        label="VOL"
        options={VOL_OPTIONS}
        value={volWindow}
        onChange={onVolWindowChange}
        formatLabel={(d) => `${d}D`}
      />

      <Divider />

      {/* 4 — RANGE */}
      <ToggleGroup
        label="RANGE"
        options={RANGE_OPTIONS}
        value={range}
        onChange={onRangeChange}
      />
    </div>
  );
}
