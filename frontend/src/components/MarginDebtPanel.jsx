import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceArea, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getMarginDebt, getTickerOverlay } from '../utils/api';

const REGIME_META = {
  froth: { label: 'FROTH / EXTREME EXPANSION', color: COLORS.red },
  neutral: { label: 'NEUTRAL', color: COLORS.amber },
  contraction: { label: 'CONTRACTION / DELEVERAGING', color: COLORS.cyan },
  capitulation: { label: 'CAPITULATION', color: COLORS.green },
};

const METHODOLOGY = (
  'Year-over-year % change of FINRA customer margin debt (total debit balances in ' +
  'securities margin accounts) — a risk-appetite / leverage / sentiment gauge. ' +
  'This is a monitoring OVERLAY: it is lagged by its ~1-month publication delay for ' +
  'all point-in-time stats and is deliberately NOT part of the 5-factor GLI composite ' +
  '(it is coincident-to-lagging and would contaminate the production liquidity signal).'
);

const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '8px 12px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber, marginBottom: 4 }}>{label}</div>
      {payload.filter(p => p.value != null).map(p => (
        <div key={p.dataKey} style={{ color: p.color || COLORS.white, display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span>{p.name}</span>
          <span>{p.dataKey === 'spy' ? p.value.toFixed(0) : `${p.value.toFixed(1)}%`}</span>
        </div>
      ))}
    </div>
  );
};

export default function MarginDebtPanel() {
  const [data, setData] = useState(null);
  const [spy, setSpy] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showMethod, setShowMethod] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      getMarginDebt().catch(e => { throw e; }),
      getTickerOverlay('SPY', '1998-01-01').catch(() => null),
    ])
      .then(([md, spyRes]) => {
        if (cancelled) return;
        setData(md);
        if (spyRes?.points) setSpy(spyRes.points);
      })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Merge margin-debt YoY% with SPY price by month
  const chartData = useMemo(() => {
    if (!data?.series) return [];
    const spyMap = {};
    (spy || []).forEach(p => { spyMap[p.date.slice(0, 7)] = p.price; });
    return data.series.map(d => ({
      date: d.date.slice(0, 7),
      yoy: d.yoy_pct,
      spy: spyMap[d.date.slice(0, 7)] ?? null,
    }));
  }, [data, spy]);

  if (loading && !data) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT, fontSize: 13 }}>Loading margin debt overlay...</div>;
  }
  if (error && !data) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.red, fontFamily: FONT, fontSize: 13 }}>Error: {error}</div>;
  }
  if (!data?.series?.length) {
    return (
      <div style={{ padding: 40, textAlign: 'center', fontFamily: FONT, fontSize: 13, color: COLORS.textMuted }}>
        No margin-debt data. Run <span style={{ color: COLORS.amber }}>backend/scripts/update_margin_debt.py</span> to populate the store.
      </div>
    );
  }

  const latest = data.latest;
  const reg = REGIME_META[latest?.regime] || { label: latest?.regime?.toUpperCase() || '—', color: COLORS.textMuted };
  const authoritative = data.meta?.is_authoritative;
  const th = data.thresholds || {};
  const yoyVals = chartData.map(d => d.yoy).filter(v => v != null);
  const yoyMin = Math.min(-25, ...yoyVals);
  const yoyMax = Math.max(35, ...yoyVals);

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1, fontWeight: 'bold' }}>
          MARGIN DEBT YoY% — LEVERAGE / SENTIMENT OVERLAY
        </span>
        <button onClick={() => setShowMethod(s => !s)}
          style={{ padding: '3px 8px', background: 'none', color: COLORS.cyan, border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
          &#8505; Methodology
        </button>
      </div>

      {showMethod && (
        <div style={{ background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, padding: '8px 12px', marginBottom: 8, fontSize: 10, color: COLORS.textMuted, lineHeight: 1.5 }}>
          {METHODOLOGY}
        </div>
      )}

      {/* Seed/placeholder banner */}
      {!authoritative && (
        <div style={{ background: '#1a1200', border: `1px solid ${COLORS.amber}66`, padding: '6px 12px', marginBottom: 8, fontSize: 10, color: COLORS.amber }}>
          ⚠ PLACEHOLDER SEED DATA — not authoritative. Run <b>backend/scripts/update_margin_debt.py</b> on a networked host to load the real FINRA series, then commit margin_debt.csv.
        </div>
      )}

      {/* Readout cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        <ReadoutCard label="MARGIN DEBT YoY%" value={latest?.yoy_pct != null ? `${latest.yoy_pct > 0 ? '+' : ''}${latest.yoy_pct.toFixed(1)}%` : '—'} color={reg.color} />
        <ReadoutCard label="EXPANDING PERCENTILE" value={latest?.percentile != null ? `${latest.percentile.toFixed(0)}th` : '—'} sub={`z = ${latest?.yoy_z != null ? latest.yoy_z.toFixed(2) : '—'}`} />
        <ReadoutCard label="REGIME" value={reg.label} color={reg.color} small />
        <ReadoutCard label="REFERENCE MONTH" value={latest?.ref_month || '—'} sub={`as of ${latest?.as_of || '—'}`} />
      </div>

      {/* Dual-axis chart: SPY (log, left) vs Margin Debt YoY% (right) */}
      <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
        S&P 500 (left, log) vs MARGIN DEBT YoY% (right, %) — shaded: expansion &gt;+{th.froth || 30}% (red), contraction &lt;0% (green)
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 15, bottom: 5, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
          <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 9, fontFamily: FONT }} interval="preserveStartEnd" minTickGap={40} />
          <YAxis yAxisId="spy" scale="log" domain={['auto', 'auto']} tick={{ fill: COLORS.textDim, fontSize: 9, fontFamily: FONT }} tickFormatter={v => v?.toFixed(0)} width={48} />
          <YAxis yAxisId="yoy" orientation="right" domain={[yoyMin, yoyMax]} tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }} tickFormatter={v => `${v}%`} width={44} />

          {/* Regime bands on the YoY axis */}
          <ReferenceArea yAxisId="yoy" y1={th.froth ?? 30} y2={yoyMax} fill={COLORS.red} fillOpacity={0.10} />
          <ReferenceArea yAxisId="yoy" y1={th.capitulation ?? -20} y2={th.neutral_low ?? 0} fill={COLORS.green} fillOpacity={0.08} />
          <ReferenceArea yAxisId="yoy" y1={yoyMin} y2={th.capitulation ?? -20} fill={COLORS.green} fillOpacity={0.16} />
          <ReferenceLine yAxisId="yoy" y={0} stroke={COLORS.textDim} strokeDasharray="2 2" />

          <Tooltip content={<ChartTooltip />} />
          <Line yAxisId="spy" type="monotone" dataKey="spy" stroke={COLORS.cyan} strokeWidth={1.5} dot={false} name="S&P 500" connectNulls />
          <Line yAxisId="yoy" type="monotone" dataKey="yoy" stroke={COLORS.amber} strokeWidth={2} dot={false} name="Margin Debt YoY%" connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ display: 'flex', gap: 14, justifyContent: 'center', fontSize: 8, color: COLORS.textDim, marginTop: 2 }}>
        <span><span style={{ color: COLORS.cyan }}>━</span> S&P 500 (log)</span>
        <span><span style={{ color: COLORS.amber }}>━</span> Margin Debt YoY%</span>
      </div>

      {/* Analytics block */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
        {/* Forward return by regime */}
        <div>
          <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
            FWD 6M S&P RETURN BY REGIME (point-in-time, lagged)
          </div>
          <table style={{ fontSize: 10, borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                {['Regime', 'N', 'Avg Fwd 6M', 'Hit %'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Regime' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 6px', fontSize: 8 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data.analytics?.forward_return_by_regime || []).map(r => (
                <tr key={r.regime} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                  <td style={{ padding: '2px 6px', color: (REGIME_META[r.regime]?.color) || COLORS.white }}>{r.regime}</td>
                  <td style={{ padding: '2px 6px', textAlign: 'right', color: COLORS.textMuted }}>{r.n}</td>
                  <td style={{ padding: '2px 6px', textAlign: 'right', color: r.avg_fwd_6m >= 0 ? COLORS.green : COLORS.red }}>{r.avg_fwd_6m > 0 ? '+' : ''}{r.avg_fwd_6m}%</td>
                  <td style={{ padding: '2px 6px', textAlign: 'right', color: COLORS.white }}>{r.hit_rate}%</td>
                </tr>
              ))}
              {(!data.analytics?.forward_return_by_regime?.length) && (
                <tr><td colSpan={4} style={{ padding: '6px', color: COLORS.textDim, fontSize: 9 }}>Needs cached SPY + GLI data (run REFRESH).</td></tr>
              )}
            </tbody>
          </table>
          <div style={{ fontSize: 8, color: COLORS.textDim, marginTop: 4 }}>
            Confirms the coincident/lagging nature — regimes use the publication-lagged series.
          </div>
        </div>

        {/* Rolling correlation with GLI composite */}
        <div>
          <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
            36M ROLLING CORR vs GLI COMPOSITE (lagged)
          </div>
          {data.analytics?.rolling_corr_gli?.length > 1 ? (
            <ResponsiveContainer width="100%" height={120}>
              <ComposedChart data={data.analytics.rolling_corr_gli} margin={{ top: 5, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 7 }} tickFormatter={d => d?.slice(0, 4)} interval="preserveStartEnd" minTickGap={30} />
                <YAxis domain={[-1, 1]} tick={{ fill: COLORS.textDim, fontSize: 8 }} width={28} />
                <ReferenceLine y={0} stroke={COLORS.textDim} strokeDasharray="2 2" />
                <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10 }} />
                <Line type="monotone" dataKey="corr" stroke={COLORS.purple} strokeWidth={1.5} dot={false} name="corr" />
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ color: COLORS.textDim, fontSize: 9, padding: 6 }}>Needs cached GLI composite (run REFRESH).</div>
          )}
          {data.analytics?.corr_note && (
            <div style={{ fontSize: 8, color: COLORS.textMuted, marginTop: 4 }}>{data.analytics.corr_note}</div>
          )}
        </div>
      </div>
    </div>
  );
}

function ReadoutCard({ label, value, sub, color, small }) {
  return (
    <div style={{ background: '#0a0a0a', padding: '8px 10px', border: `1px solid ${COLORS.cardBorder}` }}>
      <div style={{ color: COLORS.textMuted, fontSize: 8, letterSpacing: 0.5, marginBottom: 3 }}>{label}</div>
      <div style={{ color: color || COLORS.white, fontSize: small ? 11 : 18, fontWeight: 'bold', lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ color: COLORS.textDim, fontSize: 8, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
