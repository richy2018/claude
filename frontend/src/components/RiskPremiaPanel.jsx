import React, { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, ComposedChart, Area,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getRiskPremia } from '../utils/api';

const RANGES = [
  { label: '1Y', days: 252 }, { label: '2Y', days: 504 },
  { label: '5Y', days: 1260 }, { label: '10Y', days: 2520 },
  { label: '20Y', days: 5040 }, { label: 'ALL', days: 0 },
];

const ERP_COLOR = '#00ff88';
const TP_ACM_COLOR = '#ffaa00';
const TP_2S10S_COLOR = '#8844cc';

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '6px 10px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber, marginBottom: 2 }}>{d.date}</div>
      {d.erp != null && <div style={{ color: ERP_COLOR }}>ERP: {d.erp.toFixed(2)}%</div>}
      {d.tp_acm != null && <div style={{ color: TP_ACM_COLOR }}>Term Prem (ACM): {d.tp_acm.toFixed(2)}%</div>}
      {d.tp_2s10s != null && <div style={{ color: TP_2S10S_COLOR }}>2s10s Proxy: {(d.tp_2s10s * 100).toFixed(0)}bp</div>}
    </div>
  );
};

const DiffTooltip = ({ active, payload }) => {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '6px 10px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber }}>{d.date}</div>
      <div style={{ color: d.value >= 0 ? ERP_COLOR : '#ff4444' }}>
        ERP − Term Prem: {d.value != null ? `${d.value >= 0 ? '+' : ''}${d.value.toFixed(2)}%` : '—'}
      </div>
    </div>
  );
};

export default function RiskPremiaPanel() {
  const [range, setRange] = useState(2520);
  const [rangeLabel, setRangeLabel] = useState('10Y');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRiskPremia({ rangeDays: range })
      .then(r => { if (!cancelled) setData(r); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [range]);

  const btn = (active, onClick, label) => (
    <button key={label} onClick={onClick} style={{
      padding: '3px 10px', fontFamily: FONT, fontSize: 11, cursor: 'pointer',
      backgroundColor: active ? COLORS.amber : COLORS.bg,
      color: active ? COLORS.bg : COLORS.textMuted,
      border: `1px solid ${active ? COLORS.amber : COLORS.cardBorder}`,
    }}>{label}</button>
  );

  const signColor = (val, avg) => {
    if (val == null || avg == null) return COLORS.white;
    return val > avg ? COLORS.green : COLORS.red;
  };

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white, padding: '12px 0' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: COLORS.amber, letterSpacing: 2, fontWeight: 'bold' }}>
          RISK PREMIA
        </h2>
        <span style={{ fontSize: 12, color: COLORS.textMuted }}>
          Equity Risk Premium vs Bond Term Premium
        </span>
        {data && (
          <span style={{ marginLeft: 'auto', fontSize: 11, color: COLORS.textMuted }}>
            PE: {data.current_pe} | EY: {data.current_ey}%
          </span>
        )}
      </div>

      {/* Range selector */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
        <span style={{ color: COLORS.textMuted, fontSize: 11, marginRight: 4 }}>RANGE:</span>
        {RANGES.map(r => btn(
          range === r.days,
          () => { setRange(r.days); setRangeLabel(r.label); },
          r.label
        ))}
      </div>

      {loading && <div style={{ padding: 20, color: COLORS.amber, fontSize: 12 }}>Loading risk premia data...</div>}
      {error && <div style={{ padding: 20, color: COLORS.red, fontSize: 12 }}>Error: {error}</div>}

      {!loading && data && (
        <>
          {/* Top chart — ERP and Term Premium */}
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12, marginBottom: 12 }}>
            <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8 }}>
              ERP & TERM PREMIUM — {rangeLabel}
            </div>
            <div style={{ display: 'flex', gap: 16, marginBottom: 8, fontSize: 10 }}>
              <span><span style={{ color: ERP_COLOR }}>—</span> Equity Risk Premium</span>
              <span><span style={{ color: TP_ACM_COLOR }}>—</span> ACM Term Premium</span>
              <span><span style={{ color: TP_2S10S_COLOR, opacity: 0.6 }}>- -</span> 2s10s Proxy</span>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={data.top_chart} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <XAxis
                  dataKey="date"
                  tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
                  axisLine={{ stroke: COLORS.cardBorder }}
                  tickLine={false}
                  interval={Math.max(1, Math.floor((data.top_chart?.length || 1) / 10))}
                  angle={-45}
                  textAnchor="end"
                  height={45}
                />
                <YAxis
                  tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={v => `${v}%`}
                  width={45}
                />
                <Tooltip content={<CustomTooltip />} cursor={{ stroke: COLORS.textMuted, strokeDasharray: '3 3' }} />
                <ReferenceLine y={0} stroke={COLORS.textMuted} strokeDasharray="4 4" />
                <Line dataKey="erp" stroke={ERP_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line dataKey="tp_acm" stroke={TP_ACM_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line dataKey="tp_2s10s" stroke={TP_2S10S_COLOR} strokeWidth={1} strokeDasharray="6 3" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Middle chart — ERP minus Term Premium */}
          {data.diff_chart && data.diff_chart.length > 0 && (
            <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12, marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 4 }}>
                ERP MINUS TERM PREMIUM
              </div>
              <div style={{ fontSize: 10, color: COLORS.textMuted, marginBottom: 8 }}>
                Positive = equities offer more compensation than bonds. Negative = bonds more attractive.
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <ComposedChart data={data.diff_chart} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <XAxis
                    dataKey="date"
                    tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
                    axisLine={{ stroke: COLORS.cardBorder }}
                    tickLine={false}
                    interval={Math.max(1, Math.floor(data.diff_chart.length / 10))}
                    angle={-45}
                    textAnchor="end"
                    height={45}
                  />
                  <YAxis
                    tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                    axisLine={false} tickLine={false}
                    tickFormatter={v => `${v}%`}
                    width={45}
                  />
                  <Tooltip content={<DiffTooltip />} cursor={{ stroke: COLORS.textMuted, strokeDasharray: '3 3' }} />
                  <ReferenceLine y={0} stroke={COLORS.amber} strokeWidth={1} />
                  <defs>
                    <linearGradient id="diffGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={ERP_COLOR} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={ERP_COLOR} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Area dataKey="value" fill="url(#diffGrad)" stroke={ERP_COLOR} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Bottom — Summary table */}
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12 }}>
            <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8 }}>
              CURRENT READINGS
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: FONT }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['PREMIUM', 'CURRENT', '1Y AVG', '5Y AVG', 'PERCENTILE', 'Z-SCORE'].map(h => (
                    <th key={h} style={{
                      padding: '5px 8px', color: COLORS.textMuted, fontSize: 10,
                      textAlign: h === 'PREMIUM' ? 'left' : 'right', fontWeight: 'normal',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(data.summary || []).map(s => (
                  <tr key={s.name} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                    <td style={{ padding: '5px 8px', color: COLORS.white }}>{s.name}</td>
                    <td style={{
                      padding: '5px 8px', textAlign: 'right', fontWeight: 'bold',
                      color: signColor(s.current, s.hist_mean),
                    }}>
                      {s.current >= 0 ? '+' : ''}{s.current}%
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: COLORS.textSecondary }}>
                      {s.avg_1y >= 0 ? '+' : ''}{s.avg_1y}%
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: COLORS.textSecondary }}>
                      {s.avg_5y >= 0 ? '+' : ''}{s.avg_5y}%
                    </td>
                    <td style={{
                      padding: '5px 8px', textAlign: 'right',
                      color: s.percentile > 50 ? COLORS.green : COLORS.red,
                    }}>
                      {s.percentile}th
                    </td>
                    <td style={{
                      padding: '5px 8px', textAlign: 'right',
                      color: s.zscore > 0 ? COLORS.green : COLORS.red,
                    }}>
                      {s.zscore >= 0 ? '+' : ''}{s.zscore}
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
