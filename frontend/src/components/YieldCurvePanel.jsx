import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getCurveRegimes } from '../utils/api';

const PAIRS = ['10Y-2Y', '10Y-3M', '30Y-2Y', '30Y-3M', '30Y-10Y', '5Y-2Y', '5Y-3M', '2Y-3M'];
const LOOKBACKS = [5, 10, 21, 28, 63];
const RANGES = ['1M', '3M', '6M', 'YTD', '1Y', '2Y', '5Y', '10Y', 'ALL'];

function rangeToDays(r) {
  const m = { '1M': 21, '3M': 63, '6M': 126, '1Y': 252, '2Y': 504, '5Y': 1260, '10Y': 2520, 'ALL': 0 };
  if (m[r] !== undefined) return m[r];
  if (r === 'YTD') {
    const now = new Date();
    return Math.floor((now - new Date(now.getFullYear(), 0, 1)) / 86400000 * 252 / 365);
  }
  return 504;
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '6px 10px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber, marginBottom: 2 }}>{d.date}</div>
      <div style={{ color: d.color, fontWeight: 'bold' }}>{d.regime}</div>
      <div style={{ color: COLORS.white }}>Spread: {d.spread_bp}bp</div>
      <div style={{ color: COLORS.textMuted }}>Short: {d.short_yield}% | Long: {d.long_yield}%</div>
    </div>
  );
};

export default function YieldCurvePanel() {
  const [pair, setPair] = useState('10Y-2Y');
  const [lookback, setLookback] = useState(21);
  const [range, setRange] = useState('2Y');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getCurveRegimes({ pair, lookback, rangeDays: rangeToDays(range) })
      .then(r => { if (!cancelled) setData(r); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [pair, lookback, range]);

  const btn = (active, onClick, label) => (
    <button key={label} onClick={onClick} style={{
      padding: '3px 10px', fontFamily: FONT, fontSize: 11, cursor: 'pointer',
      backgroundColor: active ? COLORS.amber : COLORS.bg,
      color: active ? COLORS.bg : COLORS.textMuted,
      border: `1px solid ${active ? COLORS.amber : COLORS.cardBorder}`,
    }}>{label}</button>
  );

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white, padding: '12px 0' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: COLORS.amber, letterSpacing: 2, fontWeight: 'bold' }}>
          YIELD CURVE DYNAMICS
        </h2>
        <span style={{ fontSize: 12, color: COLORS.textMuted }}>
          {pair} Spread — Curve regime classification
        </span>
        {data && (
          <span style={{
            marginLeft: 'auto', padding: '4px 12px',
            border: `1px solid ${data.current_color}44`,
            color: data.current_color, fontSize: 11, fontWeight: 'bold',
          }}>
            {data.current_regime} | {data.current_spread_bp}bp
          </span>
        )}
      </div>

      {/* Pair selector */}
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ color: COLORS.textMuted, fontSize: 11, marginRight: 4 }}>SPREAD:</span>
        {PAIRS.map(p => btn(pair === p, () => setPair(p), p))}
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ color: COLORS.textMuted, fontSize: 11 }}>LOOKBACK:</span>
        {LOOKBACKS.map(lb => btn(lookback === lb, () => setLookback(lb), `${lb}D`))}
        <span style={{ color: COLORS.textMuted, fontSize: 11, margin: '0 6px' }}>|</span>
        <span style={{ color: COLORS.textMuted, fontSize: 11 }}>RANGE:</span>
        {RANGES.map(r => btn(range === r, () => setRange(r), r))}
      </div>

      {loading && <div style={{ padding: 20, color: COLORS.amber, fontSize: 12 }}>Loading curve data...</div>}
      {error && <div style={{ padding: 20, color: COLORS.red, fontSize: 12 }}>Error: {error}</div>}

      {!loading && data && (
        <>
          {/* Regime legend */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 10, flexWrap: 'wrap' }}>
            {Object.entries(data.regime_definitions || {}).map(([name, info]) => (
              <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10 }}>
                <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: info.color }} />
                <span style={{ color: info.color }}>{name}</span>
              </div>
            ))}
          </div>

          {/* Main chart */}
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12, marginBottom: 12 }}>
            <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8 }}>
              {pair} SPREAD — {data.total_days} days
            </div>
            <ResponsiveContainer width="100%" height={320}>
              <ComposedChart data={data.timeline} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <XAxis
                  dataKey="date"
                  tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
                  axisLine={{ stroke: COLORS.cardBorder }}
                  tickLine={false}
                  interval={Math.max(1, Math.floor(data.timeline.length / 12))}
                  angle={-45}
                  textAnchor="end"
                  height={50}
                />
                <YAxis
                  tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={v => `${v}bp`}
                  width={50}
                />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                <ReferenceLine y={0} stroke={COLORS.textMuted} strokeDasharray="4 4" />
                <Bar dataKey="spread_bp" isAnimationActive={false}>
                  {data.timeline.map((entry, i) => (
                    <Cell key={i} fill={entry.color} fillOpacity={0.7} />
                  ))}
                </Bar>
                <Line
                  dataKey="spread_bp"
                  type="monotone"
                  stroke={COLORS.amber}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* Regime frequency table */}
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12 }}>
            <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8 }}>
              REGIME FREQUENCY
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: FONT }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['REGIME', 'FREQ', 'AVG DUR',
                    `${data.short_label} CHG`, `${data.long_label} CHG`, 'SPREAD CHG'
                  ].map(h => (
                    <th key={h} style={{
                      padding: '5px 8px', color: COLORS.textMuted, fontSize: 10,
                      textAlign: h === 'REGIME' ? 'left' : 'right', fontWeight: 'normal',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.stats.map(s => (
                  <tr key={s.regime} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                    <td style={{ padding: '5px 8px' }}>
                      <span style={{ display: 'inline-block', width: 8, height: 8, backgroundColor: s.color, marginRight: 6 }} />
                      <span style={{ color: s.color }}>{s.regime}</span>
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: COLORS.white }}>{s.freq}%</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: COLORS.white }}>{s.avg_dur}d</td>
                    <td style={{
                      padding: '5px 8px', textAlign: 'right',
                      color: s.short_chg >= 0 ? '#00ff88' : '#ff4444',
                    }}>
                      {s.short_chg >= 0 ? '+' : ''}{s.short_chg}bp
                    </td>
                    <td style={{
                      padding: '5px 8px', textAlign: 'right',
                      color: s.long_chg >= 0 ? '#00ff88' : '#ff4444',
                    }}>
                      {s.long_chg >= 0 ? '+' : ''}{s.long_chg}bp
                    </td>
                    <td style={{
                      padding: '5px 8px', textAlign: 'right',
                      color: s.spread_chg >= 0 ? '#00ff88' : '#ff4444',
                    }}>
                      {s.spread_chg >= 0 ? '+' : ''}{s.spread_chg}bp
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
