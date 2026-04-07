import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Area,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliCentralBanks } from '../utils/api';

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '8px 12px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber, marginBottom: 4 }}>{label}</div>
      {payload.filter(p => p.value != null).map(p => (
        <div key={p.dataKey} style={{ color: p.color || COLORS.white, display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span>{p.name || p.dataKey}</span>
          <span>{typeof p.value === 'number' ? p.value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : p.value}</span>
        </div>
      ))}
    </div>
  );
};

export default function DollarStressPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getGliCentralBanks()
      .then(r => { if (!cancelled) setData(r); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Build non-USD CB aggregate from series data
  const chartData = useMemo(() => {
    if (!data?.series) return [];
    return data.series
      .filter(d => d.date >= '2008-01-01')
      .map(d => ({
        date: d.date,
        nonUsd: (d.ECB || 0) + (d.BoJ || 0) + (d.PBoC || 0),
        fed: d.Fed || 0,
        total: d.total || 0,
      }));
  }, [data]);

  // Compute Fed share of total
  const fedShare = useMemo(() => {
    if (!data?.summary) return null;
    const fed = data.summary.Fed?.usd_billions || 0;
    const total = Object.values(data.summary).reduce((s, v) => s + (v.usd_billions || 0), 0);
    return total > 0 ? ((fed / total) * 100).toFixed(1) : null;
  }, [data]);

  if (loading && !data) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT, fontSize: 13 }}>Loading dollar stress data...</div>;
  }

  if (data?.cached === false || (!data?.series && !loading && !error) || (error && !data)) {
    return <div style={{ padding: 60, textAlign: 'center', fontFamily: FONT, fontSize: 14, color: COLORS.textMuted }}>Click <span style={{ color: COLORS.amber }}>REFRESH</span> in the top-right to load data</div>;
  }

  const banks = data?.summary ? Object.keys(data.summary).filter(b => b !== 'Fed') : [];

  return (
    <div style={{ fontFamily: FONT }}>
      <div style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1, marginBottom: 12 }}>DOLLAR STRESS — FED vs NON-USD CB FLOWS</div>

      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 16 }}>
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '10px 12px', borderRadius: 2 }}>
          <div style={{ color: COLORS.amber, fontSize: 10, letterSpacing: 1, marginBottom: 4 }}>FED SHARE OF G4</div>
          <div style={{ color: COLORS.white, fontSize: 18 }}>{fedShare ? `${fedShare}%` : '--'}</div>
        </div>
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '10px 12px', borderRadius: 2 }}>
          <div style={{ color: COLORS.cyan, fontSize: 10, letterSpacing: 1, marginBottom: 4 }}>NON-USD CB TOTAL</div>
          <div style={{ color: COLORS.white, fontSize: 18 }}>
            {chartData.length > 0 ? `$${(chartData[chartData.length - 1].nonUsd / 1000).toFixed(1)}T` : '--'}
          </div>
        </div>
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '10px 12px', borderRadius: 2 }}>
          <div style={{ color: COLORS.green, fontSize: 10, letterSpacing: 1, marginBottom: 4 }}>G4 TOTAL</div>
          <div style={{ color: COLORS.white, fontSize: 18 }}>
            {chartData.length > 0 ? `$${(chartData[chartData.length - 1].total / 1000).toFixed(1)}T` : '--'}
          </div>
        </div>
      </div>

      {/* Fed vs non-USD chart */}
      {chartData.length > 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px', marginBottom: 12 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8, paddingLeft: 8 }}>
            FED (USD) vs NON-USD CENTRAL BANKS ($T)
          </div>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
              <XAxis
                dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={v => `${(v / 1000).toFixed(1)}T`}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone" dataKey="nonUsd" fill={COLORS.cyan} fillOpacity={0.15}
                stroke={COLORS.cyan} strokeWidth={2} dot={false} name="Non-USD CBs"
              />
              <Line
                type="monotone" dataKey="fed" stroke={COLORS.amber}
                strokeWidth={2} dot={false} name="Fed"
              />
            </ComposedChart>
          </ResponsiveContainer>
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 10, height: 2, background: COLORS.amber }} />
              <span style={{ color: COLORS.textMuted, fontSize: 10 }}>Fed (USD)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 10, height: 10, background: COLORS.cyan, opacity: 0.4, borderRadius: 1 }} />
              <span style={{ color: COLORS.textMuted, fontSize: 10 }}>Non-USD (ECB + BoJ + PBoC)</span>
            </div>
          </div>
        </div>
      )}

      {/* CB breakdown table */}
      {data?.summary && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 16px' }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8 }}>CB BREAKDOWN</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                <th style={{ textAlign: 'left', color: COLORS.textMuted, padding: '4px 8px', fontSize: 10 }}>BANK</th>
                <th style={{ textAlign: 'right', color: COLORS.textMuted, padding: '4px 8px', fontSize: 10 }}>USD ($B)</th>
                <th style={{ textAlign: 'right', color: COLORS.textMuted, padding: '4px 8px', fontSize: 10 }}>MOMENTUM</th>
                <th style={{ textAlign: 'right', color: COLORS.textMuted, padding: '4px 8px', fontSize: 10 }}>SHARE</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.summary).map(([bank, info]) => {
                const total = Object.values(data.summary).reduce((s, v) => s + (v.usd_billions || 0), 0);
                const share = total > 0 ? ((info.usd_billions || 0) / total * 100) : 0;
                const scoreClr = info.momentum_score > 70 ? COLORS.green : info.momentum_score > 30 ? COLORS.amber : COLORS.red;
                return (
                  <tr key={bank} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                    <td style={{ color: COLORS.white, padding: '6px 8px' }}>{bank}</td>
                    <td style={{ color: COLORS.white, padding: '6px 8px', textAlign: 'right' }}>
                      {info.usd_billions != null ? `$${info.usd_billions.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '--'}
                    </td>
                    <td style={{ color: scoreClr, padding: '6px 8px', textAlign: 'right' }}>
                      {info.momentum_score != null ? info.momentum_score.toFixed(0) : '--'}
                    </td>
                    <td style={{ color: COLORS.textMuted, padding: '6px 8px', textAlign: 'right' }}>
                      {share.toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data?.updated_at && (
        <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 8, textAlign: 'right' }}>
          Last updated: {new Date(data.updated_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}
