import React from 'react';
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme.js';

const PAIR_COLORS = [COLORS.white, COLORS.cyan, COLORS.amberDim];

function getPairKeys(data) {
  if (!data || data.length === 0) return [];
  const sample = data[0];
  return Object.keys(sample).filter((k) => k.includes('_vs_'));
}

function getCurrentColor(label) {
  if (!label) return COLORS.amber;
  const upper = label.toUpperCase();
  if (upper.includes('STRONGLY')) return COLORS.amber;
  if (upper.includes('MODERATE')) return COLORS.yellow;
  return COLORS.green;
}

const CustomTooltip = ({ active, payload, label, pairKeys }) => {
  if (!active || !payload || !payload.length) return null;
  return (
    <div
      style={{
        background: COLORS.card,
        border: `1px solid ${COLORS.cardBorder}`,
        padding: '8px 12px',
        fontFamily: FONT,
        fontSize: 11,
        color: COLORS.white,
      }}
    >
      <div style={{ color: COLORS.textSecondary, marginBottom: 4 }}>{label}</div>
      {payload.map((entry) => (
        <div key={entry.dataKey} style={{ color: entry.color, lineHeight: 1.6 }}>
          {entry.dataKey === 'linkage'
            ? `LINKAGE: ${entry.value != null ? entry.value.toFixed(1) : '—'}%`
            : `${entry.dataKey}: ${entry.value != null ? entry.value.toFixed(1) : '—'}%`}
        </div>
      ))}
    </div>
  );
};

export default function MarketLinkage({ linkageTimeline, currentLinkage, linkageLabel }) {
  const pairKeys = getPairKeys(linkageTimeline);
  const currentColor = getCurrentColor(linkageLabel);

  return (
    <div
      style={{
        background: COLORS.card,
        border: `1px solid ${COLORS.cardBorder}`,
        padding: '16px 20px',
        fontFamily: FONT,
      }}
    >
      {/* Title */}
      <div
        style={{
          color: COLORS.amber,
          fontSize: 13,
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          marginBottom: 10,
        }}
      >
        MARKET LINKAGE — Are all 3 assets moving together or independently?
      </div>

      {/* Explanatory text */}
      <div
        style={{
          color: COLORS.yellow,
          fontSize: 11,
          lineHeight: 1.6,
          marginBottom: 16,
          maxWidth: 820,
        }}
      >
        When the amber area is HIGH (&gt;60%), stocks, bonds, and the dollar are being driven by the
        same thing (e.g. a Fed decision or risk-on/risk-off move). When it&apos;s LOW (&lt;40%),
        each asset is moving on its own drivers. High linkage = macro-driven market. Low linkage =
        idiosyncratic moves.
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={250}>
        <ComposedChart
          data={linkageTimeline}
          margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
        >
          {/* Background */}
          <defs>
            <linearGradient id="linkageGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.amber} stopOpacity={0.28} />
              <stop offset="95%" stopColor={COLORS.amber} stopOpacity={0.04} />
            </linearGradient>
          </defs>

          <XAxis
            dataKey="date"
            tick={{ fill: COLORS.textSecondary, fontSize: 10, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: COLORS.textSecondary, fontSize: 10, fontFamily: FONT }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `${v}%`}
            width={38}
          />
          <Tooltip
            content={<CustomTooltip pairKeys={pairKeys} />}
            cursor={{ stroke: COLORS.textMuted, strokeDasharray: '3 3' }}
          />

          {/* Grid / reference lines */}
          <ReferenceLine
            y={60}
            stroke={COLORS.textMuted}
            strokeDasharray="4 4"
            label={{
              value: '60%',
              fill: COLORS.textMuted,
              fontSize: 9,
              fontFamily: FONT,
              position: 'insideTopRight',
            }}
          />
          <ReferenceLine
            y={40}
            stroke={COLORS.textMuted}
            strokeDasharray="4 4"
            label={{
              value: '40%',
              fill: COLORS.textMuted,
              fontSize: 9,
              fontFamily: FONT,
              position: 'insideBottomRight',
            }}
          />

          {/* Linkage area fill */}
          <Area
            type="monotone"
            dataKey="linkage"
            fill="url(#linkageGrad)"
            stroke={COLORS.amber}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 3, fill: COLORS.amber }}
            isAnimationActive={false}
          />

          {/* Individual correlation pair lines — derived dynamically */}
          {pairKeys.map((key, idx) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={PAIR_COLORS[idx] ?? COLORS.textSecondary}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3 }}
              isAnimationActive={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          marginTop: 10,
          fontSize: 10,
          letterSpacing: '0.06em',
          flexWrap: 'wrap',
        }}
      >
        {pairKeys.map((key, idx) => {
          const color = PAIR_COLORS[idx] ?? COLORS.textSecondary;
          const parts = key.split('_vs_');
          const label = parts.length === 2 ? `${parts[0]} vs ${parts[1]}` : key;
          return (
            <span key={key} style={{ color, display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ fontSize: 14, lineHeight: 1 }}>—</span>
              <span>{label}</span>
            </span>
          );
        })}
        <span
          style={{
            color: COLORS.amber,
            display: 'flex',
            alignItems: 'center',
            gap: 5,
          }}
        >
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              background: COLORS.amber,
              opacity: 0.7,
            }}
          />
          <span>LINKAGE</span>
        </span>
      </div>

      {/* Current reading */}
      <div
        style={{
          marginTop: 12,
          fontSize: 12,
          letterSpacing: '0.07em',
          color: currentColor,
          fontWeight: 600,
        }}
      >
        Current:{' '}
        <span style={{ color: currentColor }}>
          {currentLinkage != null ? `${currentLinkage}%` : '—'}
        </span>
        {linkageLabel ? (
          <span style={{ color: currentColor }}> — {linkageLabel}</span>
        ) : null}
      </div>
    </div>
  );
}
