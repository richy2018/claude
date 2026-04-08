import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, BarChart, Bar, Cell, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliBisCredit, refreshGli } from '../utils/api';

const RANGES = [
  { label: '10Y', days: 3650 }, { label: '20Y', days: 7300 },
  { label: 'ALL', days: 0 },
];

const COUNTRY_COLORS = [
  COLORS.amber, COLORS.cyan, COLORS.green, COLORS.red, COLORS.purple,
  COLORS.blue, COLORS.pink, COLORS.orange, '#66ff66', '#ff6666',
];

const fmt = (v) => {
  if (v == null) return '--';
  if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}T`;
  return `$${v.toFixed(0)}B`;
};

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '8px 12px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber, marginBottom: 4 }}>{label}</div>
      {payload.filter(p => p.value != null).sort((a, b) => b.value - a.value).slice(0, 8).map(p => (
        <div key={p.dataKey} style={{ color: p.color || COLORS.white, display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span>{p.dataKey}</span>
          <span>{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
};

export default function CreditCollateralPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [rangeDays, setRangeDays] = useState(7300);

  const loadData = () => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getGliBisCredit()
      .then(r => { if (!cancelled) setData(r); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  };

  useEffect(loadData, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshGli('bis');
      loadData();
    } catch (e) {
      setError(e.message);
    } finally {
      setRefreshing(false);
    }
  };

  const chartData = useMemo(() => {
    if (!data?.series) return [];
    const items = data.series;
    if (rangeDays === 0) return items;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - rangeDays);
    const cutoffStr = cutoff.toISOString().slice(0, 10);
    return items.filter(d => d.date >= cutoffStr);
  }, [data, rangeDays]);

  const countries = useMemo(() => {
    if (!data?.country_summary) return [];
    return Object.keys(data.country_summary).filter(c => c !== 'All reporting countries');
  }, [data]);

  // Build heatmap data from country z-scores
  const heatmapData = useMemo(() => {
    if (!data?.country_summary) return [];
    return Object.entries(data.country_summary)
      .filter(([c]) => c !== 'All reporting countries')
      .filter(([, info]) => info.momentum_score != null)
      .map(([country, info]) => ({
        country: country.length > 14 ? country.slice(0, 14) + '..' : country,
        fullName: country,
        score: info.momentum_score ?? 50,
        value: info.usd_billions,
      }))
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  }, [data]);

  if (loading && !data) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT, fontSize: 13 }}>Loading BIS credit data...</div>;
  }

  if (data?.cached === false || (!data?.series && !loading && !error)) {
    return <div style={{ padding: 60, textAlign: 'center', fontFamily: FONT, fontSize: 14, color: COLORS.textMuted }}>Click <span style={{ color: COLORS.amber }}>REFRESH</span> in the top-right to load data</div>;
  }

  if (error && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', fontFamily: FONT, fontSize: 13 }}>
        <div style={{ color: COLORS.red, marginBottom: 12 }}>No BIS credit data cached</div>
        <button onClick={handleRefresh} disabled={refreshing} style={{
          background: COLORS.amber, color: '#000', border: 'none', padding: '8px 20px',
          fontFamily: FONT, fontSize: 12, cursor: 'pointer', letterSpacing: 1,
        }}>
          {refreshing ? 'FETCHING...' : 'FETCH BIS DATA'}
        </button>
      </div>
    );
  }

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1 }}>CREDIT & COLLATERAL — BIS TOTAL CREDIT</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={handleRefresh} disabled={refreshing} style={{
            background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
            padding: '4px 10px', fontFamily: FONT, fontSize: 10, cursor: 'pointer', letterSpacing: 1,
          }}>
            {refreshing ? '...' : 'REFRESH'}
          </button>
          {RANGES.map(r => (
            <button key={r.label} onClick={() => setRangeDays(r.days)} style={{
              background: 'none', border: 'none',
              color: rangeDays === r.days ? COLORS.amber : COLORS.textMuted,
              fontFamily: FONT, fontSize: 11, cursor: 'pointer', padding: '4px 8px',
            }}>{r.label}</button>
          ))}
        </div>
      </div>

      {/* Total credit chart (aggregate "All reporting countries") */}
      {chartData.length > 0 && data?.country_summary?.['All reporting countries'] && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px', marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingLeft: 8, marginBottom: 8 }}>
            <span style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1 }}>GLOBAL TOTAL CREDIT TO NON-FINANCIAL SECTOR (USD)</span>
            <span style={{ color: COLORS.white, fontSize: 14 }}>
              {fmt(data.country_summary['All reporting countries']?.usd_billions)}
            </span>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
              <XAxis
                dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={v => `${(v / 1000).toFixed(0)}T`}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone" dataKey="All reporting countries" fill={COLORS.amber} fillOpacity={0.1}
                stroke={COLORS.amber} strokeWidth={2} dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Country z-score heatmap */}
      {heatmapData.length > 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px', marginBottom: 12 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8, paddingLeft: 8 }}>
            COUNTRY CREDIT MOMENTUM (Z-SCORE 0-100)
          </div>
          <ResponsiveContainer width="100%" height={Math.max(200, heatmapData.length * 28)}>
            <BarChart data={heatmapData} layout="vertical" margin={{ top: 5, right: 20, bottom: 5, left: 90 }}>
              <XAxis type="number" domain={[0, 100]} tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} />
              <YAxis type="category" dataKey="country" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} width={75} />
              <Tooltip
                formatter={(v) => `${v?.toFixed(1)}/100`}
                labelStyle={{ color: COLORS.amber, fontFamily: FONT }}
                contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 11 }}
              />
              <Bar dataKey="score" radius={[0, 2, 2, 0]}>
                {heatmapData.map((entry, i) => (
                  <Cell key={i} fill={entry.score > 70 ? COLORS.green : entry.score > 30 ? COLORS.amber : COLORS.red} fillOpacity={0.7} />
                ))}
              </Bar>
              <ReferenceLine x={50} stroke={COLORS.textDim} strokeDasharray="3 3" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Diffusion index */}
      {data?.diffusion?.length > 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px' }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8, paddingLeft: 8 }}>
            CREDIT DIFFUSION INDEX (% OF COUNTRIES IMPROVING)
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={data.diffusion.slice(-120)} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
              <XAxis
                dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd"
              />
              <YAxis domain={[0, 100]} tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} />
              <Tooltip
                formatter={(v) => `${v?.toFixed(1)}%`}
                labelStyle={{ color: COLORS.amber, fontFamily: FONT }}
                contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 11 }}
              />
              <ReferenceLine y={50} stroke={COLORS.textDim} strokeDasharray="3 3" />
              <Line
                type="monotone" dataKey="diffusion_weighted" stroke={COLORS.amber}
                strokeWidth={2} dot={false} name="GDP-Weighted"
              />
              <Line
                type="monotone" dataKey="diffusion" stroke={COLORS.cyan}
                strokeWidth={1.5} strokeDasharray="6 3" dot={false} name="Unweighted"
              />
            </ComposedChart>
          </ResponsiveContainer>
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 14, height: 2, background: COLORS.amber }} />
              <span style={{ color: COLORS.textMuted, fontSize: 10 }}>GDP-Weighted</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 14, height: 0, borderTop: `2px dashed ${COLORS.cyan}` }} />
              <span style={{ color: COLORS.textMuted, fontSize: 10 }}>Unweighted</span>
            </div>
            <span style={{ color: COLORS.textDim, fontSize: 9 }}>Divergence = small countries expanding, large not</span>
          </div>
        </div>
      )}

      {/* Debt/Liquidity Ratio */}
      {data?.debt_ratio?.ratio_series?.length > 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px', marginTop: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingLeft: 8, marginBottom: 8 }}>
            <span style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1 }}>
              DEBT / LIQUIDITY RATIO (TOTAL CREDIT / CB BALANCE SHEETS)
            </span>
            <span style={{
              color: data.debt_ratio.zone === 'crisis' ? COLORS.red :
                     data.debt_ratio.zone === 'stress' ? COLORS.amber : COLORS.green,
              fontSize: 14,
            }}>
              {data.debt_ratio.current_ratio?.toFixed(2)}x
              <span style={{ fontSize: 10, marginLeft: 6 }}>
                ({data.debt_ratio.zone?.toUpperCase()})
              </span>
            </span>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <ComposedChart data={data.debt_ratio.ratio_series} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
              <XAxis
                dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                domain={['dataMin', 'dataMax']}
                tickFormatter={v => `${v?.toFixed(1)}x`}
              />
              <Tooltip
                formatter={(v, name) => [`${v?.toFixed(3)}${name === 'ratio' ? 'x' : ''}`, name === 'ratio' ? 'Ratio' : 'YoY RoC']}
                labelStyle={{ color: COLORS.amber, fontFamily: FONT }}
                contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 11 }}
              />
              <ReferenceLine y={2.0} stroke={COLORS.amber} strokeDasharray="6 3" label={{ value: 'Stress 2.0x', fill: COLORS.amber, fontSize: 9, position: 'right' }} />
              <ReferenceLine y={2.3} stroke={COLORS.red} strokeDasharray="6 3" label={{ value: 'Crisis 2.3x', fill: COLORS.red, fontSize: 9, position: 'right' }} />
              <Line
                type="monotone" dataKey="ratio" stroke={COLORS.white}
                strokeWidth={2} dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>

          {/* Rate of Change subplot */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingLeft: 8, marginTop: 12, marginBottom: 4 }}>
            <span style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1 }}>
              RATE OF CHANGE (YoY) — positive = tightening, negative = loosening
            </span>
            {data.debt_ratio.current_roc != null && (
              <span style={{
                color: data.debt_ratio.roc_signal === 'tightening' ? COLORS.red : COLORS.green,
                fontSize: 12,
              }}>
                {data.debt_ratio.current_roc > 0 ? '+' : ''}{data.debt_ratio.current_roc.toFixed(3)}
                <span style={{ fontSize: 10, marginLeft: 4 }}>
                  ({data.debt_ratio.roc_signal?.toUpperCase()})
                </span>
              </span>
            )}
          </div>
          <ResponsiveContainer width="100%" height={140}>
            <ComposedChart data={data.debt_ratio.ratio_series.filter(d => d.roc != null)} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
              <XAxis
                dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={v => v?.toFixed(2)}
              />
              <Tooltip
                formatter={(v) => v?.toFixed(3)}
                labelStyle={{ color: COLORS.amber, fontFamily: FONT }}
                contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 11 }}
              />
              <ReferenceLine y={0} stroke={COLORS.textDim} strokeDasharray="3 3" />
              <Area
                type="monotone" dataKey="roc" dot={false}
                stroke="none" fillOpacity={0.3}
                fill="url(#rocGradient)"
              />
              <Line type="monotone" dataKey="roc" stroke={COLORS.white} strokeWidth={1.5} dot={false} />
              <defs>
                <linearGradient id="rocGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COLORS.red} stopOpacity={0.6} />
                  <stop offset="50%" stopColor={COLORS.red} stopOpacity={0.05} />
                  <stop offset="50%" stopColor={COLORS.green} stopOpacity={0.05} />
                  <stop offset="100%" stopColor={COLORS.green} stopOpacity={0.6} />
                </linearGradient>
              </defs>
            </ComposedChart>
          </ResponsiveContainer>
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 4 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 10, height: 10, background: COLORS.red, opacity: 0.4 }} />
              <span style={{ color: COLORS.textMuted, fontSize: 9 }}>Tightening (risk-off)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 10, height: 10, background: COLORS.green, opacity: 0.4 }} />
              <span style={{ color: COLORS.textMuted, fontSize: 9 }}>Loosening (risk-on)</span>
            </div>
          </div>
        </div>
      )}

      {data?.updated_at && (
        <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 8, textAlign: 'right' }}>
          Last updated: {new Date(data.updated_at).toLocaleString()} | BIS data has ~4 month lag
        </div>
      )}
    </div>
  );
}
