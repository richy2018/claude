import { useState, useMemo } from 'react';
import {
  ComposedChart,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Area,
  Cell,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';

/* ─────────────────────────────────────────────────────────────
   Helpers
───────────────────────────────────────────────────────────── */

function fmtMonYY(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + (dateStr.length === 7 ? '-01' : ''));
  if (isNaN(d)) return dateStr;
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
}

function fmtPct(v, decimals = 2) {
  if (v == null) return '—';
  return parseFloat(v).toFixed(decimals) + '%';
}

function filterByRange(arr, range) {
  if (!arr || arr.length === 0) return arr || [];
  if (range === 'ALL') return arr;

  const sorted = [...arr].sort((a, b) => (a.date > b.date ? 1 : -1));

  if (range === '1M') return sorted.slice(-1);
  if (range === '3M') return sorted.slice(-3);
  if (range === '6M') return sorted.slice(-6);
  if (range === '1Y') return sorted.slice(-12);
  if (range === '2Y') return sorted.slice(-24);
  if (range === '5Y') return sorted.slice(-60);

  if (range === 'YTD') {
    const year = new Date().getFullYear();
    return sorted.filter((d) => d.date && d.date.startsWith(String(year)));
  }

  return sorted;
}

/* ─────────────────────────────────────────────────────────────
   Shared sub-components
───────────────────────────────────────────────────────────── */

function SectionTitle({ children }) {
  return (
    <div style={{
      fontSize: 12,
      color: COLORS.amber,
      fontWeight: 'bold',
      letterSpacing: 2,
      fontFamily: FONT,
    }}>
      {children}
    </div>
  );
}

function RangeButton({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: FONT,
        fontSize: 10,
        letterSpacing: 1,
        padding: '2px 7px',
        border: `1px solid ${active ? COLORS.amber : COLORS.cardBorder}`,
        backgroundColor: active ? `${COLORS.amber}22` : 'transparent',
        color: active ? COLORS.amber : COLORS.textMuted,
        cursor: 'pointer',
        outline: 'none',
      }}
    >
      {label}
    </button>
  );
}

function ModeButton({ label, active, disabled }) {
  return (
    <button
      disabled={disabled}
      style={{
        fontFamily: FONT,
        fontSize: 10,
        letterSpacing: 1,
        padding: '2px 7px',
        border: `1px solid ${active ? COLORS.cyan : COLORS.cardBorder}`,
        backgroundColor: active ? `${COLORS.cyan}18` : 'transparent',
        color: active ? COLORS.cyan : COLORS.textMuted,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        outline: 'none',
      }}
    >
      {label}
    </button>
  );
}

function AttrButton({ active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: FONT,
        fontSize: 10,
        letterSpacing: 1,
        padding: '2px 7px',
        border: `1px solid ${active ? COLORS.yellow : COLORS.cardBorder}`,
        backgroundColor: active ? `${COLORS.yellow}18` : 'transparent',
        color: active ? COLORS.yellow : COLORS.textMuted,
        cursor: 'pointer',
        outline: 'none',
      }}
    >
      ATTR
    </button>
  );
}

function PaceToggleButton({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: FONT,
        fontSize: 10,
        letterSpacing: 1,
        padding: '2px 8px',
        border: `1px solid ${active ? COLORS.white : COLORS.cardBorder}`,
        backgroundColor: active ? `${COLORS.white}14` : 'transparent',
        color: active ? COLORS.white : COLORS.textMuted,
        cursor: 'pointer',
        outline: 'none',
      }}
    >
      {label}
    </button>
  );
}

const AXIS_STYLE = {
  fontFamily: FONT,
  fontSize: 10,
  fill: COLORS.textMuted,
};

const TOOLTIP_STYLE = {
  backgroundColor: COLORS.bgDark,
  border: `1px solid ${COLORS.cardBorder}`,
  fontFamily: FONT,
  fontSize: 11,
  color: COLORS.white,
  padding: '8px 12px',
};

function YoyTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div style={TOOLTIP_STYLE}>
      <div style={{ color: COLORS.textMuted, marginBottom: 4 }}>{fmtMonYY(label)}</div>
      {payload.map((p) => {
        if (p.value == null) return null;
        return (
          <div key={p.dataKey} style={{ color: p.color }}>
            {p.name}: {fmtPct(p.value)}
          </div>
        );
      })}
    </div>
  );
}

function MomTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div style={TOOLTIP_STYLE}>
      <div style={{ color: COLORS.textMuted, marginBottom: 4 }}>{fmtMonYY(label)}</div>
      {payload.map((p) => {
        if (p.value == null) return null;
        return (
          <div key={p.dataKey} style={{ color: parseFloat(p.value) >= 0 ? COLORS.green : COLORS.red }}>
            MoM: {fmtPct(p.value)}
          </div>
        );
      })}
    </div>
  );
}

function DecompTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div style={TOOLTIP_STYLE}>
      <div style={{ color: COLORS.textMuted, marginBottom: 4 }}>{fmtMonYY(label)}</div>
      {payload.map((p) => {
        if (p.value == null) return null;
        return (
          <div key={p.dataKey} style={{ color: p.color || COLORS.white }}>
            {p.name}: {fmtPct(p.value)}
          </div>
        );
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Legend row
───────────────────────────────────────────────────────────── */

function LegendRow({ items }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px 16px', marginTop: 8 }}>
      {items.map((item) => (
        <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {item.dashed ? (
            <svg width={22} height={10}>
              <line
                x1={0} y1={5} x2={22} y2={5}
                stroke={item.color}
                strokeWidth={1.5}
                strokeDasharray="6 3"
              />
            </svg>
          ) : (
            <svg width={22} height={10}>
              <line x1={0} y1={5} x2={22} y2={5} stroke={item.color} strokeWidth={item.thick ? 2 : 1.5} />
            </svg>
          )}
          <span style={{ fontSize: 10, color: COLORS.textMuted, fontFamily: FONT }}>{item.label}</span>
        </div>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Section 1 — YOY INFLATION chart
───────────────────────────────────────────────────────────── */

const RANGES = ['1M', '3M', '6M', 'YTD', '1Y', '2Y', '5Y', 'ALL'];
const MODES = ['MOM->YOY', 'YOY SPEED', 'FF RATE', 'SWAP FIX'];

function YoySection({ data, range, onRangeChange }) {
  const [attrOn, setAttrOn] = useState(false);

  const chartData = useMemo(() => {
    if (!data) return [];

    // Build a date-keyed map
    const map = {};

    // Historical yoy
    const filteredHist = filterByRange(data.yoy_history || [], range);
    filteredHist.forEach((pt) => {
      map[pt.date] = { date: pt.date, yoy_actual: pt.yoy, proj_1m: null, proj_2m: null, proj_3m: null };
    });

    // Projections
    const lastHistDate = filteredHist.length > 0 ? filteredHist[filteredHist.length - 1].date : null;

    ['1m_pace', '2m_pace', '3m_pace'].forEach((key, idx) => {
      const projKey = ['proj_1m', 'proj_2m', 'proj_3m'][idx];
      (data.projections?.[key] || []).forEach((pt) => {
        if (!map[pt.date]) {
          map[pt.date] = { date: pt.date, yoy_actual: null, proj_1m: null, proj_2m: null, proj_3m: null };
        }
        map[pt.date][projKey] = pt.projected_yoy;
      });
    });

    // Stitch: the last historical point should also be the first projection point for visual continuity
    if (lastHistDate && map[lastHistDate]) {
      ['proj_1m', 'proj_2m', 'proj_3m'].forEach((key, idx) => {
        const paceKey = ['1m_pace', '2m_pace', '3m_pace'][idx];
        const firstProj = (data.projections?.[paceKey] || [])[0];
        if (firstProj && map[lastHistDate]) {
          // Only set if not already set
          if (map[lastHistDate][key] == null) {
            map[lastHistDate][key] = map[lastHistDate].yoy_actual;
          }
        }
      });
    }

    return Object.values(map).sort((a, b) => (a.date > b.date ? 1 : -1));
  }, [data, range]);

  if (!data) return null;

  const latestMom = parseFloat(data.latest_mom || 0).toFixed(2);
  const latestYoy = parseFloat(data.latest_yoy || 0).toFixed(2);
  const latestIndex = parseFloat(data.latest_index || 0).toFixed(3);

  return (
    <div style={{ padding: '14px 16px' }}>
      {/* Header info row */}
      <div style={{
        fontSize: 11,
        color: COLORS.amber,
        fontFamily: FONT,
        marginBottom: 10,
        letterSpacing: 0.5,
      }}>
        LATEST: {data.latest_date_label} | Index: {latestIndex} | MoM: +{latestMom}% | YoY: {latestYoy}%
      </div>

      {/* Title + controls row */}
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 8 }}>
        <SectionTitle>YOY INFLATION</SectionTitle>

        {/* Range buttons */}
        <div style={{ display: 'flex', gap: 3 }}>
          {RANGES.map((r) => (
            <RangeButton key={r} label={r} active={range === r} onClick={() => onRangeChange(r)} />
          ))}
        </div>

        {/* Mode buttons */}
        <div style={{ display: 'flex', gap: 3 }}>
          {MODES.map((m) => (
            <ModeButton key={m} label={m} active={m === 'MOM->YOY'} disabled={m !== 'MOM->YOY'} />
          ))}
        </div>

        <AttrButton active={attrOn} onClick={() => setAttrOn((v) => !v)} />
      </div>

      {/* Description */}
      <div style={{
        fontSize: 11,
        color: COLORS.white,
        fontFamily: FONT,
        marginBottom: 10,
        opacity: 0.75,
      }}>
        Model A: Grows index at recent MoM pace (1M/2M/3M avg), computes YoY vs actual index 12mo prior
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={250}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={fmtMonYY}
            tick={AXIS_STYLE}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            tick={AXIS_STYLE}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            tickFormatter={(v) => v.toFixed(1) + '%'}
            width={44}
          />
          <Tooltip content={<YoyTooltip />} />
          <ReferenceLine
            y={2}
            stroke={COLORS.red}
            strokeDasharray="5 4"
            label={{ value: '2% Target', fill: COLORS.red, fontSize: 10, fontFamily: FONT, position: 'insideTopRight' }}
          />
          <Line
            type="monotone"
            dataKey="yoy_actual"
            name="YoY actual"
            stroke={COLORS.amber}
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="proj_1m"
            name="1M MoM"
            stroke={COLORS.blue}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="proj_2m"
            name="2M MoM avg"
            stroke={COLORS.red}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="proj_3m"
            name="3M MoM avg"
            stroke={COLORS.green}
            strokeWidth={1.5}
            strokeDasharray="6 3"
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <LegendRow items={[
        { label: 'YoY actual', color: COLORS.amber, thick: true },
        { label: '1M MoM', color: COLORS.blue },
        { label: '2M MoM avg', color: COLORS.red },
        { label: '3M MoM avg', color: COLORS.green, dashed: true },
        { label: '2% Target', color: COLORS.red, dashed: true },
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Section 2 — MOM % bar chart
───────────────────────────────────────────────────────────── */

function MomSection({ data, range }) {
  const [attrOn, setAttrOn] = useState(false);

  const momData = useMemo(() => {
    return filterByRange(data?.mom_history || [], range);
  }, [data, range]);

  if (!data) return null;

  return (
    <div style={{ padding: '14px 16px', borderTop: `1px solid ${COLORS.cardBorder}` }}>
      {/* Title + ATTR */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <SectionTitle>MOM % — Historical month-over-month changes</SectionTitle>
        <AttrButton active={attrOn} onClick={() => setAttrOn((v) => !v)} />
      </div>

      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={momData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={fmtMonYY}
            tick={AXIS_STYLE}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            tick={AXIS_STYLE}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            tickFormatter={(v) => v.toFixed(2) + '%'}
            width={50}
          />
          <Tooltip content={<MomTooltip />} />
          <ReferenceLine y={0} stroke={COLORS.cardBorder} />
          <Bar dataKey="mom" name="MoM" isAnimationActive={false}>
            {momData.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={parseFloat(entry.mom) >= 0 ? COLORS.green : COLORS.red}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Section 3 — Projection Decomposition
───────────────────────────────────────────────────────────── */

const PACE_OPTIONS = [
  { key: '1m_pace', label: '1M PACE' },
  { key: '2m_pace', label: '2M AVG' },
  { key: '3m_pace', label: '3M AVG' },
];

function DecompSection({ data, range }) {
  const [selectedPace, setSelectedPace] = useState('2m_pace');
  const [attrOn, setAttrOn] = useState(false);

  const chartData = useMemo(() => {
    if (!data) return [];

    const map = {};

    // Use tail of yoy_history (last 12 for context regardless of range)
    const histTail = filterByRange(data.yoy_history || [], range);
    histTail.forEach((pt) => {
      map[pt.date] = {
        date: pt.date,
        yoy_actual: pt.yoy,
        proj_1m: null,
        proj_2m: null,
        proj_3m: null,
        base_effect_favorable: null,
        base_effect_unfavorable: null,
      };
    });

    const lastHistDate = histTail.length > 0 ? histTail[histTail.length - 1].date : null;

    // Projections for all 3 paces
    ['1m_pace', '2m_pace', '3m_pace'].forEach((key, idx) => {
      const projKey = ['proj_1m', 'proj_2m', 'proj_3m'][idx];
      (data.projections?.[key] || []).forEach((pt) => {
        if (!map[pt.date]) {
          map[pt.date] = {
            date: pt.date,
            yoy_actual: null,
            proj_1m: null,
            proj_2m: null,
            proj_3m: null,
            base_effect_favorable: null,
            base_effect_unfavorable: null,
          };
        }
        map[pt.date][projKey] = pt.projected_yoy;
      });
    });

    // Stitch last hist point into projections for continuity
    if (lastHistDate && map[lastHistDate]) {
      ['proj_1m', 'proj_2m', 'proj_3m'].forEach((projKey) => {
        if (map[lastHistDate][projKey] == null) {
          map[lastHistDate][projKey] = map[lastHistDate].yoy_actual;
        }
      });
    }

    // Base effects for selected pace (only in projection period)
    (data.base_effects?.[selectedPace] || []).forEach((pt) => {
      if (!map[pt.date]) {
        map[pt.date] = {
          date: pt.date,
          yoy_actual: null,
          proj_1m: null,
          proj_2m: null,
          proj_3m: null,
          base_effect_favorable: null,
          base_effect_unfavorable: null,
        };
      }
      const absVal = Math.abs(parseFloat(pt.base_effect || 0));
      if (pt.favorable) {
        map[pt.date].base_effect_favorable = absVal;
      } else {
        map[pt.date].base_effect_unfavorable = absVal;
      }
    });

    return Object.values(map).sort((a, b) => (a.date > b.date ? 1 : -1));
  }, [data, range, selectedPace]);

  if (!data) return null;

  return (
    <div style={{ padding: '14px 16px', borderTop: `1px solid ${COLORS.cardBorder}` }}>
      {/* Title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <SectionTitle>PROJECTION DECOMPOSITION (A+B)</SectionTitle>
        <AttrButton active={attrOn} onClick={() => setAttrOn((v) => !v)} />
      </div>

      {/* Description */}
      <div style={{
        fontSize: 10,
        color: COLORS.yellow,
        fontFamily: FONT,
        marginBottom: 10,
        lineHeight: 1.5,
        opacity: 0.85,
      }}>
        Same 3 MoM speed projections as above. Bars show monthly base effects (old MoM dropping off the 12-month window)
        anchored at the selected speed&apos;s annualized rate — green = favorable (hot month exits), red = unfavorable.
      </div>

      {/* Pace toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 10, color: COLORS.textMuted, fontFamily: FONT, letterSpacing: 1 }}>
          BASE EFFECTS FOR:
        </span>
        {PACE_OPTIONS.map(({ key, label }) => (
          <PaceToggleButton
            key={key}
            label={label}
            active={selectedPace === key}
            onClick={() => setSelectedPace(key)}
          />
        ))}
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={250}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={fmtMonYY}
            tick={AXIS_STYLE}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            tick={AXIS_STYLE}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            tickFormatter={(v) => v.toFixed(1) + '%'}
            width={44}
          />
          <Tooltip content={<DecompTooltip />} />
          <ReferenceLine
            y={2}
            stroke={COLORS.red}
            strokeDasharray="5 4"
            label={{ value: '2% Target', fill: COLORS.red, fontSize: 10, fontFamily: FONT, position: 'insideTopRight' }}
          />

          {/* Base effect bars — rendered before lines so lines sit on top */}
          <Bar
            dataKey="base_effect_favorable"
            name="Favorable base effect"
            fill={`${COLORS.green}55`}
            stroke={COLORS.green}
            strokeWidth={0.5}
            isAnimationActive={false}
            barSize={14}
          />
          <Bar
            dataKey="base_effect_unfavorable"
            name="Unfavorable base effect"
            fill={`${COLORS.red}55`}
            stroke={COLORS.red}
            strokeWidth={0.5}
            isAnimationActive={false}
            barSize={14}
          />

          {/* Projection + actual lines */}
          <Line
            type="monotone"
            dataKey="yoy_actual"
            name="YoY actual"
            stroke={COLORS.amber}
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="proj_1m"
            name="1M MoM"
            stroke={COLORS.blue}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="proj_2m"
            name="2M MoM avg"
            stroke={COLORS.red}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="proj_3m"
            name="3M MoM avg"
            stroke={COLORS.green}
            strokeWidth={1.5}
            strokeDasharray="6 3"
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <LegendRow items={[
        { label: 'YoY actual', color: COLORS.amber, thick: true },
        { label: '1M MoM', color: COLORS.blue },
        { label: '2M MoM avg', color: COLORS.red },
        { label: '3M MoM avg', color: COLORS.green, dashed: true },
        { label: '2% Target', color: COLORS.red, dashed: true },
        { label: 'Favorable base effect', color: COLORS.green },
        { label: 'Unfavorable base effect', color: COLORS.red },
      ]} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Main InflationModelView component
───────────────────────────────────────────────────────────── */

export default function InflationModelView({ data }) {
  const [range, setRange] = useState('1Y');

  if (!data) {
    return (
      <div style={{
        fontFamily: FONT,
        color: COLORS.textMuted,
        fontSize: 13,
        padding: '24px 16px',
      }}>
        No inflation model data available.
      </div>
    );
  }

  return (
    <div style={{
      fontFamily: FONT,
      color: COLORS.white,
      backgroundColor: COLORS.bg,
      border: `1px solid ${COLORS.cardBorder}`,
    }}>
      {/* Section 1 — YOY INFLATION */}
      <YoySection data={data} range={range} onRangeChange={setRange} />

      {/* Section 2 — MOM % bar chart */}
      <MomSection data={data} range={range} />

      {/* Section 3 — Projection Decomposition */}
      <DecompSection data={data} range={range} />
    </div>
  );
}
