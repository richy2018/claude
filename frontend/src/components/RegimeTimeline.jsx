import React, { useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { COLORS, FONT, REGIME_COLORS, REGIME_LABELS } from '../utils/theme.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SPX_COLOR  = '#e0e0e0';
const RATES_COLOR = COLORS.amber;   // '#d4830a'
const DXY_COLOR  = COLORS.cyan;     // '#00e5ff'

const MAX_STRIP_SEGMENTS = 600; // cap for the color strip

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Sample an array down to at most `maxLen` evenly-spaced items.
 * Always includes the first and last element.
 */
function sampleArray(arr, maxLen) {
  if (arr.length <= maxLen) return arr;
  const result = [];
  const step = (arr.length - 1) / (maxLen - 1);
  for (let i = 0; i < maxLen; i++) {
    result.push(arr[Math.round(i * step)]);
  }
  return result;
}

/**
 * Format a date string for axis ticks (MMM YY).
 */
function formatAxisDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
}

/**
 * Format a full date for the tooltip (YYYY-MM-DD).
 */
function formatTooltipDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  return d.toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Custom Tooltip
// ---------------------------------------------------------------------------

function RegimeTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;

  const dataPoint = payload[0]?.payload ?? {};
  const regime    = dataPoint.regime ?? '';
  const regimeLabel = REGIME_LABELS[regime] ?? regime;
  const regimeColor = REGIME_COLORS[regime] ?? COLORS.textSecondary;

  const rowStyle = {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '16px',
    fontSize: '11px',
    fontFamily: FONT,
    color: COLORS.white,
    margin: '2px 0',
  };

  const labelStyle = { color: COLORS.textSecondary };

  const getValue = (key) => {
    const entry = payload.find((p) => p.dataKey === key);
    if (entry == null || entry.value == null) return '—';
    return entry.value.toFixed(2);
  };

  return (
    <div
      style={{
        background: '#111111',
        border: `1px solid ${COLORS.cardBorder}`,
        padding: '8px 12px',
        fontFamily: FONT,
        minWidth: '220px',
      }}
    >
      {/* Date */}
      <div
        style={{
          fontSize: '11px',
          color: COLORS.amberLight,
          fontFamily: FONT,
          marginBottom: '4px',
          letterSpacing: '0.05em',
        }}
      >
        {formatTooltipDate(label)}
      </div>

      {/* Regime label */}
      <div
        style={{
          fontSize: '10px',
          fontFamily: FONT,
          color: regimeColor,
          marginBottom: '6px',
          borderBottom: `1px solid ${COLORS.cardBorder}`,
          paddingBottom: '4px',
        }}
      >
        {regime} — {regimeLabel}
      </div>

      {/* Metric rows */}
      <div style={rowStyle}>
        <span style={{ ...labelStyle, color: SPX_COLOR }}>SPX</span>
        <span>{getValue('spx_metric')}</span>
      </div>
      <div style={rowStyle}>
        <span style={{ ...labelStyle, color: RATES_COLOR }}>10Y</span>
        <span>{getValue('rates_metric')}</span>
      </div>
      <div style={rowStyle}>
        <span style={{ ...labelStyle, color: DXY_COLOR }}>DXY</span>
        <span>{getValue('dxy_metric')}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Regime Color Strip
// ---------------------------------------------------------------------------

function RegimeColorStrip({ timeline }) {
  const segments = useMemo(
    () => sampleArray(timeline, MAX_STRIP_SEGMENTS),
    [timeline]
  );

  if (!segments || segments.length === 0) return null;

  return (
    <div
      style={{
        display: 'flex',
        width: '100%',
        height: '20px',
        overflow: 'hidden',
        margin: '0 0 2px 0',
        flexShrink: 0,
      }}
      title="Regime color by date"
    >
      {segments.map((point, i) => {
        const color =
          point.color ?? REGIME_COLORS[point.regime] ?? COLORS.textMuted;
        return (
          <div
            key={i}
            style={{
              flex: '1 1 0',
              background: color,
              minWidth: '1px',
            }}
          />
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function RegimeTimeline({ timeline = [], title = '' }) {
  // Determine tick interval so we don't crowd the x-axis
  const tickInterval = useMemo(() => {
    const n = timeline.length;
    if (n <= 30)  return 0;           // show every tick
    if (n <= 90)  return Math.ceil(n / 12);
    if (n <= 365) return Math.ceil(n / 12);
    return Math.ceil(n / 12);
  }, [timeline.length]);

  // Container styles
  const containerStyle = {
    background: COLORS.bg,
    border: `1px solid ${COLORS.cardBorder}`,
    padding: '0',
    fontFamily: FONT,
    display: 'flex',
    flexDirection: 'column',
    userSelect: 'none',
  };

  // Title bar
  const titleBarStyle = {
    background: COLORS.bgDark,
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    padding: '6px 12px',
    fontSize: '11px',
    fontFamily: FONT,
    color: COLORS.amber,
    letterSpacing: '0.1em',
    textTransform: 'uppercase',
    flexShrink: 0,
  };

  // Chart wrapper
  const chartWrapperStyle = {
    padding: '8px 4px 4px 4px',
    flex: '0 0 auto',
  };

  // Legend
  const legendStyle = {
    display: 'flex',
    gap: '20px',
    padding: '6px 12px 8px',
    borderTop: `1px solid ${COLORS.cardBorder}`,
    flexShrink: 0,
  };

  const legendItemStyle = {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    fontSize: '10px',
    fontFamily: FONT,
    color: COLORS.textSecondary,
    letterSpacing: '0.05em',
  };

  const dashStyle = (color) => ({
    display: 'inline-block',
    width: '18px',
    height: '2px',
    background: color,
    flexShrink: 0,
  });

  const axisTickStyle = {
    fill: COLORS.textMuted,
    fontSize: 9,
    fontFamily: FONT,
  };

  return (
    <div style={containerStyle}>
      {/* 1. Title bar */}
      <div style={titleBarStyle}>
        REGIME TIMELINE{title ? ` \u2014 ${title}` : ''}
      </div>

      {/* 2. Regime color strip */}
      <div style={{ padding: '8px 12px 0' }}>
        <RegimeColorStrip timeline={timeline} />
      </div>

      {/* 3. Main chart */}
      <div style={chartWrapperStyle}>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart
            data={timeline}
            margin={{ top: 8, right: 16, bottom: 32, left: 8 }}
          >
            {/* X Axis */}
            <XAxis
              dataKey="date"
              tick={{ ...axisTickStyle, textAnchor: 'end' }}
              angle={-45}
              interval={tickInterval}
              tickFormatter={formatAxisDate}
              axisLine={{ stroke: COLORS.cardBorder }}
              tickLine={{ stroke: COLORS.cardBorder }}
              dy={6}
            />

            {/* Y Axis */}
            <YAxis
              tick={axisTickStyle}
              axisLine={{ stroke: COLORS.cardBorder }}
              tickLine={{ stroke: COLORS.cardBorder }}
              tickFormatter={(v) => v.toFixed(1)}
              width={42}
            />

            {/* Zero reference line */}
            <ReferenceLine
              y={0}
              stroke={COLORS.textMuted}
              strokeDasharray="4 4"
              strokeWidth={1}
            />

            {/* Custom tooltip */}
            <Tooltip
              content={<RegimeTooltip />}
              cursor={{ stroke: COLORS.textMuted, strokeWidth: 1, strokeDasharray: '3 3' }}
            />

            {/* SPX metric */}
            <Line
              type="monotone"
              dataKey="spx_metric"
              stroke={SPX_COLOR}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3, fill: SPX_COLOR, strokeWidth: 0 }}
              isAnimationActive={false}
            />

            {/* Rates (10Y) metric */}
            <Line
              type="monotone"
              dataKey="rates_metric"
              stroke={RATES_COLOR}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3, fill: RATES_COLOR, strokeWidth: 0 }}
              isAnimationActive={false}
            />

            {/* DXY metric */}
            <Line
              type="monotone"
              dataKey="dxy_metric"
              stroke={DXY_COLOR}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3, fill: DXY_COLOR, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* 4. Legend */}
      <div style={legendStyle}>
        <div style={legendItemStyle}>
          <span style={dashStyle(SPX_COLOR)} />
          SPX
        </div>
        <div style={legendItemStyle}>
          <span style={dashStyle(RATES_COLOR)} />
          10Y
        </div>
        <div style={legendItemStyle}>
          <span style={dashStyle(DXY_COLOR)} />
          DXY
        </div>
      </div>
    </div>
  );
}
