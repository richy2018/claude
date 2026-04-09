import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getComponentDetail } from '../utils/api';

const PAIR_COLORS = {
  'EUR/USD': COLORS.cyan,
  'JPY/USD': COLORS.amber,
  'GBP/USD': COLORS.green,
  'CHF/USD': COLORS.purple,
  'KRW/USD': COLORS.pink,
};

const BASIS_RANGES = [
  { label: '3M', months: 3 }, { label: '6M', months: 6 },
  { label: '1Y', months: 12 }, { label: '2Y', months: 24 }, { label: 'ALL', months: 0 },
];

export default function DollarFundingPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [basisRange, setBasisRange] = useState(12);
  const [showWeights, setShowWeights] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getComponentDetail()
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(e => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  const basisHistory = useMemo(() => {
    if (!data?.basis_swaps?.history) return [];
    const items = data.basis_swaps.history;
    if (basisRange === 0) return items;
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - basisRange);
    const cutoffStr = cutoff.toISOString().slice(0, 10);
    return items.filter(d => d.date >= cutoffStr);
  }, [data, basisRange]);

  if (loading) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT, fontSize: 13 }}>Loading dollar funding data...</div>;
  }

  if (error) {
    return <div style={{ padding: 16, color: COLORS.red, fontSize: 11, background: '#1a0000', border: `1px solid ${COLORS.red}`, fontFamily: FONT }}>{error}</div>;
  }

  if (!data) return null;

  const alert = data.alert || {};
  const pairs = data.basis_swaps?.pairs || [];
  const dsIndex = data.dollar_stress_index || {};

  const alertIcon = (level) => {
    if (level === 'LOW') return { emoji: '\u{1F7E2}', color: COLORS.green };
    if (level === 'ELEVATED') return { emoji: '\u{1F7E1}', color: COLORS.amber };
    if (level === 'HIGH') return { emoji: '\u{1F534}', color: COLORS.red };
    return { emoji: '\u26AB', color: COLORS.red };
  };

  const dollarIcon = alertIcon(alert.dollar_funding?.level);

  // Change columns: positive change = stress easing = green, negative = stress increasing = red
  const chgColor = (v) => {
    if (v == null) return COLORS.textDim;
    return v > 0 ? COLORS.green : v < 0 ? COLORS.red : COLORS.textMuted;
  };

  const stressColor = (level) => {
    if (level === 'LOW') return COLORS.green;
    if (level === 'MODERATE') return COLORS.amber;
    if (level === 'ELEVATED') return COLORS.orange;
    return COLORS.red;
  };

  // Current basis level: positive/near-zero = green (easy $), negative = stress
  const basisColor = (v) => {
    if (v == null) return COLORS.textMuted;
    if (v > 0) return COLORS.green;
    if (v > -10) return COLORS.green;
    if (v > -30) return COLORS.amber;
    return COLORS.red;
  };

  const trendLabel = (t) => {
    if (t === 'loosening') return { text: '\u2193 Loosening', color: COLORS.green };
    if (t === 'tightening') return { text: '\u2191 Tightening', color: COLORS.red };
    return { text: '\u2192 Stable', color: COLORS.textMuted };
  };

  const RangeSelector = ({ ranges, current, onChange }) => (
    <div style={{ display: 'flex', gap: 4 }}>
      {ranges.map(r => (
        <button key={r.label} onClick={() => onChange(r.months)} style={{
          padding: '2px 8px', background: current === r.months ? COLORS.amber + '33' : 'none',
          color: current === r.months ? COLORS.amber : COLORS.textDim,
          border: `1px solid ${current === r.months ? COLORS.amber + '44' : COLORS.cardBorder}`,
          fontFamily: FONT, fontSize: 9, cursor: 'pointer',
        }}>{r.label}</button>
      ))}
    </div>
  );

  return (
    <div style={{ fontFamily: FONT }}>
      {/* ═══ Alert Status ═══ */}
      <div style={{
        background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
        padding: '12px 16px', marginBottom: 16,
      }}>
        <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 4 }}>DOLLAR FUNDING ALERT</div>
        <div style={{ color: COLORS.textDim, fontSize: 8, marginBottom: 6, fontStyle: 'italic' }}>
          Monitoring only — the production signal (3FA) uses Qty + Credit + M2. Dollar Stress is not in the composite.
        </div>
        <div style={{ display: 'flex', gap: 32, marginBottom: 8 }}>
          <div>
            <span style={{ fontSize: 11, marginRight: 8 }}>Dollar Funding:</span>
            <span style={{ color: dollarIcon.color, fontWeight: 'bold', fontSize: 12 }}>
              {dollarIcon.emoji} {alert.dollar_funding?.level} STRESS
            </span>
          </div>
        </div>
        <div style={{ fontSize: 10, color: COLORS.textSecondary, lineHeight: 1.6 }}>
          {alert.text}
        </div>
      </div>

      {/* ═══ Cross-Currency Basis Swaps ═══ */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1, fontWeight: 'bold' }}>
              CROSS-CURRENCY BASIS SWAPS
            </span>
            {dsIndex.current != null && (
              <span style={{ fontSize: 10, color: COLORS.textMuted }}>
                Dollar Stress Index:{' '}
                <span style={{ color: dsIndex.current > 15 ? COLORS.red : dsIndex.current > 5 ? COLORS.amber : COLORS.green, fontWeight: 'bold' }}>
                  {dsIndex.current?.toFixed(2)}
                </span>
                {' '}({dsIndex.direction})
              </span>
            )}
          </div>
          <RangeSelector ranges={BASIS_RANGES} current={basisRange} onChange={setBasisRange} />
        </div>

        {/* Basis Swap Table */}
        {pairs.length > 0 && (
          <div style={{ overflowX: 'auto', marginBottom: 12 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: FONT }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['Pair', 'Current (bp)', '1W Chg', '1M Chg', '3M Chg', '6M Chg', 'Trend', 'Stress Level'].map(h => (
                    <th key={h} style={{
                      padding: '4px 8px', textAlign: h === 'Pair' || h === 'Trend' || h === 'Stress Level' ? 'left' : 'right',
                      color: COLORS.textMuted, fontSize: 9, letterSpacing: 0.5, background: COLORS.bgDark, whiteSpace: 'nowrap',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pairs.map((p, i) => {
                  const tr = trendLabel(p.trend);
                  return (
                    <tr key={p.pair} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`, background: i % 2 === 0 ? COLORS.card : 'transparent' }}>
                      <td style={{ padding: '4px 8px', color: PAIR_COLORS[p.pair] || COLORS.white, fontWeight: 700 }}>{p.pair}</td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: basisColor(p.current), fontWeight: 'bold' }}>{p.current != null ? `${p.current > 0 ? '+' : ''}${p.current.toFixed(1)}` : '--'}</td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: chgColor(p.chg_1w) }}>{p.chg_1w != null ? `${p.chg_1w > 0 ? '+' : ''}${p.chg_1w.toFixed(1)}` : '--'}</td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: chgColor(p.chg_1m) }}>{p.chg_1m != null ? `${p.chg_1m > 0 ? '+' : ''}${p.chg_1m.toFixed(1)}` : '--'}</td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: chgColor(p.chg_3m) }}>{p.chg_3m != null ? `${p.chg_3m > 0 ? '+' : ''}${p.chg_3m.toFixed(1)}` : '--'}</td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: chgColor(p.chg_6m) }}>{p.chg_6m != null ? `${p.chg_6m > 0 ? '+' : ''}${p.chg_6m.toFixed(1)}` : '--'}</td>
                      <td style={{ padding: '4px 8px', color: tr.color }}>{tr.text}</td>
                      <td style={{ padding: '4px 8px', color: stressColor(p.stress), fontWeight: 'bold', fontSize: 9 }}>{p.stress}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Basis Swap Chart */}
        {basisHistory.length > 1 && (
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '8px', marginBottom: 8 }}>
            <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4, paddingLeft: 4 }}>
              CROSS-CURRENCY BASIS SWAPS (bp)
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={basisHistory} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 9, fontFamily: FONT }}
                  tickFormatter={d => d?.slice(5, 10)} interval="preserveStartEnd" />
                <YAxis tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
                  tickFormatter={v => `${v}bp`} />
                <Tooltip
                  formatter={(v, name) => [`${v?.toFixed(1)} bp`, name]}
                  contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10 }}
                  labelStyle={{ color: COLORS.amber }}
                />
                <ReferenceLine y={0} stroke={COLORS.textDim} strokeDasharray="3 3" />
                <ReferenceLine y={-40} stroke={COLORS.red} strokeDasharray="6 3" strokeOpacity={0.4} />
                {Object.entries(PAIR_COLORS).map(([pair, color]) => (
                  <Line key={pair} type="monotone" dataKey={pair} stroke={color}
                    strokeWidth={1.5} dot={false} name={pair} connectNulls />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 4 }}>
              {Object.entries(PAIR_COLORS).map(([pair, color]) => (
                <div key={pair} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                  <div style={{ width: 12, height: 2, background: color }} />
                  <span style={{ color: COLORS.textDim, fontSize: 8 }}>{pair}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Dollar Stress Index Chart */}
        {dsIndex.history?.length > 1 && (
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '8px' }}>
            <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4, paddingLeft: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
              DOLLAR STRESS INDEX (weighted composite — higher = more stress)
              <span onClick={() => setShowWeights(!showWeights)} style={{
                cursor: 'pointer', color: COLORS.cyan, fontSize: 10, userSelect: 'none',
                border: `1px solid ${COLORS.cyan}44`, borderRadius: 8, width: 16, height: 16,
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              }} title="Show currency weights">&#8505;</span>
            </div>
            {showWeights && (
              <div style={{
                background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`,
                padding: '8px 12px', marginBottom: 8, fontSize: 10, lineHeight: 1.8,
              }}>
                <div style={{ color: COLORS.amber, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>BIS-INFORMED CURRENCY WEIGHTS</div>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  {[
                    { pair: 'EUR/USD', weight: '40%' },
                    { pair: 'JPY/USD', weight: '30%' },
                    { pair: 'GBP/USD', weight: '12%' },
                    { pair: 'CHF/USD', weight: '10%' },
                    { pair: 'KRW/USD', weight: '8%' },
                  ].map(w => (
                    <span key={w.pair}>
                      <span style={{ color: PAIR_COLORS[w.pair] || COLORS.white }}>{w.pair}</span>
                      <span style={{ color: COLORS.textSecondary }}> {w.weight}</span>
                    </span>
                  ))}
                </div>
                <div style={{ color: COLORS.textDim, fontSize: 8, marginTop: 4, lineHeight: 1.6 }}>
                  Weights reflect cross-border dollar funding relevance (BIS), not GDP.
                  JPY and CHF are overweighted vs GDP because Japanese institutions are the largest
                  foreign holders of USD assets and Swiss banks are disproportionate dollar intermediaries.
                  Index = negative of weighted average basis (higher = more dollar stress).
                </div>
              </div>
            )}
            <ResponsiveContainer width="100%" height={220}>
              <ComposedChart data={(() => {
                if (basisRange === 0) return dsIndex.history;
                const cutoff = new Date();
                cutoff.setMonth(cutoff.getMonth() - basisRange);
                const cutStr = cutoff.toISOString().slice(0, 10);
                return dsIndex.history.filter(d => d.date >= cutStr);
              })()} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 9, fontFamily: FONT }}
                  tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
                <YAxis tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }} />
                <Tooltip
                  formatter={(v) => [v?.toFixed(2), 'Stress Index']}
                  contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10 }}
                  labelStyle={{ color: COLORS.amber }}
                />
                <ReferenceLine y={0} stroke={COLORS.textDim} strokeDasharray="3 3" />
                <Area type="monotone" dataKey="value" stroke={COLORS.amber} fill={COLORS.amber}
                  fillOpacity={0.1} strokeWidth={2} dot={false} name="Dollar Stress" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
