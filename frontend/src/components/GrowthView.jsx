import { useState, useEffect, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, BarChart, Bar, ComposedChart, Cell,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getFairValue } from '../utils/api';

/* ─────────────────────────────────────────────────────────────
   Formatting helpers
───────────────────────────────────────────────────────────── */

function fmtDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d)) return dateStr;
  return d.toLocaleDateString('en-US', { year: '2-digit', month: 'short' });
}

function fmtPct(v) {
  if (v == null) return '—';
  return parseFloat(v).toFixed(2) + '%';
}

function fmtK(v) {
  if (v == null) return '—';
  const n = parseFloat(v);
  return (n >= 0 ? '+' : '') + n.toFixed(0) + 'k';
}

/* ─────────────────────────────────────────────────────────────
   Custom tooltips
───────────────────────────────────────────────────────────── */

function YoyTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div style={{
      background: COLORS.bgDark,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: '6px 10px',
      fontFamily: FONT,
      fontSize: 11,
      color: COLORS.white,
    }}>
      <div style={{ color: COLORS.textMuted, marginBottom: 2 }}>{fmtDate(label)}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {fmtPct(p.value)}
        </div>
      ))}
    </div>
  );
}

function Chg3mTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  const val = payload[0]?.value;
  return (
    <div style={{
      background: COLORS.bgDark,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: '6px 10px',
      fontFamily: FONT,
      fontSize: 11,
      color: COLORS.white,
    }}>
      <div style={{ color: COLORS.textMuted, marginBottom: 2 }}>{fmtDate(label)}</div>
      <div style={{ color: val >= 0 ? COLORS.green : COLORS.red }}>
        3m Chg: {fmtK(val)}
      </div>
    </div>
  );
}

function ProjectionTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div style={{
      background: COLORS.bgDark,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: '6px 10px',
      fontFamily: FONT,
      fontSize: 11,
      color: COLORS.white,
    }}>
      <div style={{ color: COLORS.textMuted, marginBottom: 2 }}>{fmtDate(label)}</div>
      {payload.map((p) => {
        if (p.value == null) return null;
        return (
          <div key={p.dataKey} style={{ color: p.fill || p.stroke || COLORS.white }}>
            {p.name}: {typeof p.value === 'number' ? fmtPct(p.value) : p.value}
          </div>
        );
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Section 1 — YoY Employment Line Chart
───────────────────────────────────────────────────────────── */

function YoyChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={fmtDate}
            tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={(v) => v.toFixed(1) + '%'}
            tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            width={38}
          />
          <Tooltip content={<YoyTooltip />} />
          <ReferenceLine y={0} stroke={COLORS.cardBorder} strokeDasharray="3 3" />
          <Line
            type="monotone"
            dataKey="yoy"
            stroke={COLORS.cyan}
            strokeWidth={1.5}
            dot={false}
            name="YoY"
          />
        </LineChart>
      </ResponsiveContainer>
  );
}

/* ─────────────────────────────────────────────────────────────
   Section 2 — 3-Month Change Bar Chart
───────────────────────────────────────────────────────────── */

function Chg3mChart({ data }) {
  const displayed = useMemo(() => data.slice(-60), [data]);

  return (
    <div style={{
      background: COLORS.bgDark,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: '12px 14px',
      marginBottom: 2,
    }}>
      <div style={{
        fontFamily: FONT,
        fontSize: 10,
        color: COLORS.amber,
        letterSpacing: '0.08em',
        marginBottom: 10,
      }}>
        3-MONTH CHANGE (OUTRIGHT)
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={displayed} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={fmtDate}
            tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={(v) => v.toFixed(0) + 'k'}
            tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            width={42}
          />
          <Tooltip content={<Chg3mTooltip />} />
          <ReferenceLine y={0} stroke={COLORS.cardBorder} />
          <Bar dataKey="value" name="3m Chg" isAnimationActive={false}>
            {displayed.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.value >= 0 ? COLORS.green : COLORS.red}
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

function ProjectionChart({ payrolls }) {
  const [selectedPace, setSelectedPace] = useState('2m_pace');

  // Build unified dataset: last 24 months of actual + projection forward
  const chartData = useMemo(() => {
    if (!payrolls) return [];

    const yoyHistory = payrolls.yoy_history || [];
    const recent = yoyHistory.slice(-24);

    // Map actuals by date
    const byDate = {};
    recent.forEach((pt) => {
      byDate[pt.date] = { date: pt.date, yoy_actual: pt.yoy };
    });

    // Merge projection lines
    const projections = payrolls.projections || {};
    (['1m_pace', '2m_pace', '3m_pace']).forEach((pace) => {
      const series = projections[pace] || [];
      series.forEach((pt) => {
        if (!byDate[pt.date]) byDate[pt.date] = { date: pt.date };
        byDate[pt.date][`proj_${pace}`] = pt.projected_yoy;
      });
    });

    // Merge base effects for selected pace
    const baseEffects = (payrolls.base_effects || {})[selectedPace] || [];
    baseEffects.forEach((pt) => {
      if (!byDate[pt.date]) byDate[pt.date] = { date: pt.date };
      byDate[pt.date].base_effect = pt.base_effect;
      byDate[pt.date].favorable = pt.favorable;
    });

    return Object.values(byDate).sort((a, b) => (a.date > b.date ? 1 : -1));
  }, [payrolls, selectedPace]);

  return (
    <div style={{
      background: COLORS.bgDark,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: '12px 14px',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ fontFamily: FONT, fontSize: 10, color: COLORS.amber, letterSpacing: '0.08em' }}>
          PROJECTION DECOMPOSITION (A+B)
        </div>
        {/* ATTR button placeholder */}
        <button
          style={{
            background: 'transparent',
            border: `1px solid ${COLORS.cardBorder}`,
            color: COLORS.textMuted,
            fontFamily: FONT,
            fontSize: 9,
            padding: '2px 8px',
            cursor: 'default',
            letterSpacing: '0.06em',
          }}
        >
          ATTR
        </button>
      </div>

      {/* Description */}
      <div style={{
        fontFamily: FONT,
        fontSize: 10,
        color: COLORS.yellow,
        marginBottom: 8,
        lineHeight: 1.5,
      }}>
        Same 3 MoM speed projections as above. Bars show monthly base effects (old MoM dropping off
        the 12-month window) anchored at the selected speed&apos;s annualized rate — green = favorable
        (hot month exits), red = unfavorable.
      </div>

      {/* Pace toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
        <span style={{ fontFamily: FONT, fontSize: 9, color: COLORS.textMuted, letterSpacing: '0.06em' }}>
          BASE EFFECTS FOR:
        </span>
        {PACE_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => setSelectedPace(opt.key)}
            style={{
              background: selectedPace === opt.key ? COLORS.amber : 'transparent',
              border: `1px solid ${selectedPace === opt.key ? COLORS.amber : COLORS.cardBorder}`,
              color: selectedPace === opt.key ? COLORS.bgDark : COLORS.textMuted,
              fontFamily: FONT,
              fontSize: 9,
              padding: '2px 8px',
              cursor: 'pointer',
              letterSpacing: '0.06em',
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginBottom: 6, flexWrap: 'wrap' }}>
        {[
          { color: COLORS.amber,  label: 'YoY Actual', dash: false },
          { color: COLORS.blue,   label: '1M Pace Proj', dash: false },
          { color: COLORS.red,    label: '2M Avg Proj', dash: false },
          { color: COLORS.green,  label: '3M Avg Proj', dash: true },
        ].map((item) => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{
              width: 18,
              height: 2,
              background: item.color,
              borderTop: item.dash ? `2px dashed ${item.color}` : undefined,
              opacity: item.dash ? 0.9 : 1,
            }} />
            <span style={{ fontFamily: FONT, fontSize: 9, color: COLORS.textMuted }}>
              {item.label}
            </span>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <div style={{ width: 18, height: 2, borderTop: `2px dashed ${COLORS.red}` }} />
          <span style={{ fontFamily: FONT, fontSize: 9, color: COLORS.textMuted }}>2% Target</span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={chartData} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="date"
            tickFormatter={fmtDate}
            tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={(v) => v.toFixed(1) + '%'}
            tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            width={38}
          />
          <Tooltip content={<ProjectionTooltip />} />

          {/* 2% target reference line */}
          <ReferenceLine y={2} stroke={COLORS.red} strokeDasharray="4 3" strokeWidth={1} />

          {/* Base effect bars — favorable (green) */}
          <Bar
            dataKey="base_effect"
            name="Base Effect"
            isAnimationActive={false}
            maxBarSize={14}
          >
            {chartData.map((entry, index) => (
              <Cell
                key={`be-${index}`}
                fill={entry.favorable ? `${COLORS.green}55` : `${COLORS.red}55`}
              />
            ))}
          </Bar>

          {/* YoY Actual — amber, solid */}
          <Line
            type="monotone"
            dataKey="yoy_actual"
            stroke={COLORS.amber}
            strokeWidth={2}
            dot={false}
            name="YoY Actual"
            connectNulls={false}
          />

          {/* 1M Pace projection — blue */}
          <Line
            type="monotone"
            dataKey="proj_1m_pace"
            stroke={COLORS.blue}
            strokeWidth={1.5}
            dot={false}
            name="1M Pace"
            connectNulls={false}
          />

          {/* 2M Avg projection — red */}
          <Line
            type="monotone"
            dataKey="proj_2m_pace"
            stroke={COLORS.red}
            strokeWidth={1.5}
            dot={false}
            name="2M Avg"
            connectNulls={false}
          />

          {/* 3M Avg projection — green dashed */}
          <Line
            type="monotone"
            dataKey="proj_3m_pace"
            stroke={COLORS.green}
            strokeWidth={1.5}
            strokeDasharray="5 3"
            dot={false}
            name="3M Avg"
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Stats row (latest payrolls summary)
───────────────────────────────────────────────────────────── */

function LatestStats({ latest }) {
  if (!latest) return null;
  const items = [
    { label: 'LEVEL',    value: latest.level != null ? (latest.level / 1000).toFixed(0) + 'k' : '—', color: COLORS.white },
    { label: 'MOM CHG',  value: latest.mom_chg != null ? (latest.mom_chg >= 0 ? '+' : '') + latest.mom_chg + 'k' : '—',
      color: latest.mom_chg >= 0 ? COLORS.green : COLORS.red },
    { label: 'YOY',      value: fmtPct(latest.yoy_pct),
      color: latest.yoy_pct >= 0 ? COLORS.cyan : COLORS.red },
    { label: '3M CHG',   value: latest.chg_3m != null ? (latest.chg_3m >= 0 ? '+' : '') + latest.chg_3m + 'k' : '—',
      color: latest.chg_3m >= 0 ? COLORS.green : COLORS.red },
    { label: 'DATE',     value: fmtDate(latest.date), color: COLORS.textMuted },
  ];

  return (
    <div style={{
      display: 'flex',
      gap: 20,
      padding: '8px 14px',
      background: COLORS.card,
      border: `1px solid ${COLORS.cardBorder}`,
      marginBottom: 2,
      flexWrap: 'wrap',
    }}>
      {items.map((item) => (
        <div key={item.label} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontFamily: FONT, fontSize: 9, color: COLORS.textMuted, letterSpacing: '0.06em' }}>
            {item.label}
          </span>
          <span style={{ fontFamily: FONT, fontSize: 13, color: item.color, fontWeight: 600 }}>
            {item.value}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Main GrowthView component
───────────────────────────────────────────────────────────── */

export default function GrowthView() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getFairValue('growth')
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message || 'Failed to load growth data');
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, []);

  /* ── container ── */
  const containerStyle = {
    fontFamily: FONT,
    background: COLORS.bg,
    color: COLORS.white,
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    padding: 0,
  };

  /* ── header bar ── */
  const subTabs = ['CPI MODEL', 'PCE MODEL', 'PPI MODEL', 'SWAP DYNAMICS', 'GROWTH', 'TRIANGULATION'];

  if (loading) {
    return (
      <div style={{ ...containerStyle, padding: 24, alignItems: 'center', justifyContent: 'center', minHeight: 400 }}>
        <span style={{ color: COLORS.amber, fontSize: 12, letterSpacing: '0.1em' }}>
          Loading growth data...
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...containerStyle, padding: 24, alignItems: 'center', justifyContent: 'center', minHeight: 400 }}>
        <span style={{ color: COLORS.red, fontSize: 12 }}>Error: {error}</span>
      </div>
    );
  }

  const payrolls = data?.payrolls || {};

  return (
    <div style={containerStyle}>

      {/* ── FAIR VALUE MODEL header + sub-tab strip ── */}
      <div style={{
        background: COLORS.card,
        border: `1px solid ${COLORS.cardBorder}`,
        padding: '10px 14px 0 14px',
        marginBottom: 2,
      }}>
        <div style={{
          fontSize: 10,
          color: COLORS.amber,
          letterSpacing: '0.1em',
          marginBottom: 8,
          fontFamily: FONT,
        }}>
          FAIR VALUE MODEL
        </div>

        {/* Sub-tab strip (display only — active tab highlighted) */}
        <div style={{ display: 'flex', gap: 0, borderBottom: `1px solid ${COLORS.cardBorder}` }}>
          {subTabs.map((tab) => {
            const isActive = tab === 'GROWTH';
            return (
              <div
                key={tab}
                style={{
                  fontFamily: FONT,
                  fontSize: 9,
                  color: isActive ? COLORS.amber : COLORS.textMuted,
                  borderBottom: isActive ? `2px solid ${COLORS.amber}` : '2px solid transparent',
                  padding: '4px 10px 6px 10px',
                  letterSpacing: '0.06em',
                  cursor: 'default',
                  userSelect: 'none',
                  whiteSpace: 'nowrap',
                }}
              >
                {tab}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── SECTION 1: YoY Employment Growth line chart ── */}
      <div style={{
        background: COLORS.card,
        border: `1px solid ${COLORS.cardBorder}`,
        padding: '12px 14px',
        marginBottom: 2,
      }}>
        <div style={{ fontFamily: FONT, fontSize: 10, color: COLORS.amber, letterSpacing: '0.08em', marginBottom: 10 }}>
          YOY EMPLOYMENT GROWTH
        </div>
        <YoyChart data={payrolls.yoy_history || []} />
      </div>

      {/* ── Latest stats ── */}
      <LatestStats latest={payrolls.latest} />

      {/* ── SECTION 2: 3m Change bars ── */}
      <Chg3mChart data={payrolls.chg_3m_history || []} />

      {/* ── SECTION 3: Projection Decomposition ── */}
      <ProjectionChart payrolls={payrolls} />

    </div>
  );
}
