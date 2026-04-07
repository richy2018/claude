import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliFedNet, refreshGli } from '../utils/api';

const RANGES = [
  { label: '1Y', days: 365 }, { label: '2Y', days: 730 },
  { label: '5Y', days: 1825 }, { label: 'ALL', days: 0 },
];

const COMPONENT_COLORS = {
  WALCL: COLORS.amber,
  CURRCIR: COLORS.red,
  RRPONTSYD: COLORS.cyan,
  WTREGEN: COLORS.purple,
};

const COMPONENT_LABELS = {
  WALCL: 'Fed Total Assets',
  CURRCIR: 'Currency in Circ.',
  RRPONTSYD: 'Reverse Repo (RRP)',
  WTREGEN: 'Treasury Gen. Acct (TGA)',
};

const fmt = (v) => {
  if (v == null) return '--';
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}B`;
};

const fmtChange = (v) => {
  if (v == null) return '--';
  const sign = v >= 0 ? '+' : '';
  return `${sign}$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}B`;
};

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '8px 12px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber, marginBottom: 4 }}>{label}</div>
      {payload.filter(p => p.value != null).map(p => (
        <div key={p.dataKey} style={{ color: p.color || COLORS.white, display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span>{COMPONENT_LABELS[p.dataKey] || p.dataKey}</span>
          <span>{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
};

export default function USFundingPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [rangeDays, setRangeDays] = useState(730);

  const loadData = () => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getGliFedNet()
      .then(r => { if (!cancelled) setData(r); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  };

  useEffect(loadData, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshGli('fed');
      loadData();
    } catch (e) {
      setError(e.message);
    } finally {
      setRefreshing(false);
    }
  };

  // Filter data by range
  const chartData = useMemo(() => {
    if (!data?.components) return [];
    const items = data.components;
    if (rangeDays === 0) return items;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - rangeDays);
    const cutoffStr = cutoff.toISOString().slice(0, 10);
    return items.filter(d => d.date >= cutoffStr);
  }, [data, rangeDays]);

  const latest = data?.latest;

  if (loading && !data) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT, fontSize: 13 }}>Loading Fed net liquidity...</div>;
  }

  if (error && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', fontFamily: FONT, fontSize: 13 }}>
        <div style={{ color: COLORS.red, marginBottom: 12 }}>No Fed liquidity data cached</div>
        <button onClick={handleRefresh} disabled={refreshing} style={{
          background: COLORS.amber, color: '#000', border: 'none', padding: '8px 20px',
          fontFamily: FONT, fontSize: 12, cursor: 'pointer', letterSpacing: 1,
        }}>
          {refreshing ? 'FETCHING...' : 'FETCH FED DATA'}
        </button>
      </div>
    );
  }

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 24, alignItems: 'baseline' }}>
          <span style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1 }}>FED NET LIQUIDITY</span>
          {latest && (
            <span style={{ color: COLORS.white, fontSize: 18 }}>{fmt(latest.net_liquidity)}</span>
          )}
          {latest && (
            <span style={{ color: latest.wow_change >= 0 ? COLORS.green : COLORS.red, fontSize: 12 }}>
              WoW {fmtChange(latest.wow_change)}
            </span>
          )}
          {latest && (
            <span style={{ color: latest.mom_change >= 0 ? COLORS.green : COLORS.red, fontSize: 12 }}>
              MoM {fmtChange(latest.mom_change)}
            </span>
          )}
        </div>
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

      {/* Component metrics cards */}
      {latest && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
          {Object.entries(COMPONENT_LABELS).map(([key, label]) => (
            <div key={key} style={{
              background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
              padding: '10px 12px', borderRadius: 2,
            }}>
              <div style={{ color: COMPONENT_COLORS[key], fontSize: 10, letterSpacing: 1, marginBottom: 4 }}>{label}</div>
              <div style={{ color: COLORS.white, fontSize: 16 }}>{fmt(latest[key.toLowerCase()] ?? latest[key])}</div>
            </div>
          ))}
        </div>
      )}

      {/* Net liquidity chart */}
      {chartData.length > 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px', marginBottom: 12 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8, paddingLeft: 8 }}>
            NET LIQUIDITY = WALCL - CURRCIR - RRP - TGA ($B)
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
                domain={['dataMin', 'dataMax']}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone" dataKey="net_liquidity" fill={COLORS.amber} fillOpacity={0.1}
                stroke={COLORS.amber} strokeWidth={2} dot={false} name="Net Liquidity"
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Component breakdown chart */}
      {chartData.length > 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px' }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8, paddingLeft: 8 }}>
            COMPONENT BREAKDOWN ($B)
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
                tickFormatter={v => `${(v / 1000).toFixed(1)}T`}
              />
              <Tooltip content={<CustomTooltip />} />
              {Object.entries(COMPONENT_COLORS).map(([key, color]) => (
                <Line
                  key={key} type="monotone" dataKey={key}
                  stroke={color} strokeWidth={1.5} dot={false}
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
          {/* Legend */}
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 8 }}>
            {Object.entries(COMPONENT_LABELS).map(([key, label]) => (
              <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 10, height: 2, background: COMPONENT_COLORS[key] }} />
                <span style={{ color: COLORS.textMuted, fontSize: 10 }}>{label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data info */}
      {data?.updated_at && (
        <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 8, textAlign: 'right' }}>
          Last updated: {new Date(data.updated_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}
