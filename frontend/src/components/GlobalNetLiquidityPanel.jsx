import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliCentralBanks, refreshGli } from '../utils/api';

const RANGES = [
  { label: '5Y', days: 1825 }, { label: '10Y', days: 3650 },
  { label: 'ALL', days: 0 },
];

const CB_COLORS = {
  Fed: COLORS.amber,
  ECB: COLORS.cyan,
  BoJ: COLORS.green,
  PBoC: COLORS.red,
};

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
      {payload.filter(p => p.value != null).sort((a, b) => b.value - a.value).map(p => (
        <div key={p.dataKey} style={{ color: p.color, display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span>{p.dataKey}</span>
          <span>{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
};

export default function GlobalNetLiquidityPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [rangeDays, setRangeDays] = useState(3650);

  const loadData = () => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getGliCentralBanks()
      .then(r => { if (!cancelled) setData(r); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  };

  useEffect(loadData, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshGli('cb');
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

  if (loading && !data) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT, fontSize: 13 }}>Loading central bank data...</div>;
  }

  if (error && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', fontFamily: FONT, fontSize: 13 }}>
        <div style={{ color: COLORS.red, marginBottom: 12 }}>No CB balance sheet data cached</div>
        <button onClick={handleRefresh} disabled={refreshing} style={{
          background: COLORS.amber, color: '#000', border: 'none', padding: '8px 20px',
          fontFamily: FONT, fontSize: 12, cursor: 'pointer', letterSpacing: 1,
        }}>
          {refreshing ? 'FETCHING...' : 'FETCH CB DATA'}
        </button>
      </div>
    );
  }

  const banks = data?.summary ? Object.keys(data.summary) : [];

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1 }}>GLOBAL CENTRAL BANK BALANCE SHEETS (USD)</span>
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

      {/* Summary cards */}
      {data?.summary && (
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${banks.length}, 1fr)`, gap: 8, marginBottom: 16 }}>
          {banks.map(bank => {
            const s = data.summary[bank];
            const score = s?.momentum_score;
            const scoreColor = score == null ? COLORS.textMuted : score > 70 ? COLORS.green : score > 30 ? COLORS.amber : COLORS.red;
            return (
              <div key={bank} style={{
                background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
                padding: '10px 12px', borderRadius: 2,
              }}>
                <div style={{ color: CB_COLORS[bank] || COLORS.white, fontSize: 11, letterSpacing: 1, marginBottom: 4 }}>{bank}</div>
                <div style={{ color: COLORS.white, fontSize: 16 }}>{fmt(s?.usd_billions)}</div>
                {score != null && (
                  <div style={{ color: scoreColor, fontSize: 10, marginTop: 2 }}>
                    Momentum: {score.toFixed(0)}/100
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Stacked area chart */}
      {chartData.length > 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px' }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8, paddingLeft: 8 }}>
            COMBINED CB BALANCE SHEETS (USD TRILLIONS)
          </div>
          <ResponsiveContainer width="100%" height={360}>
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
              {banks.map(bank => (
                <Area
                  key={bank} type="monotone" dataKey={bank} stackId="cb"
                  fill={CB_COLORS[bank] || COLORS.blue} fillOpacity={0.3}
                  stroke={CB_COLORS[bank] || COLORS.blue} strokeWidth={1}
                />
              ))}
              <Line
                type="monotone" dataKey="total" stroke={COLORS.white}
                strokeWidth={2} strokeDasharray="4 2" dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
          {/* Legend */}
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 8 }}>
            {banks.map(bank => (
              <div key={bank} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 10, height: 10, background: CB_COLORS[bank] || COLORS.blue, opacity: 0.6, borderRadius: 1 }} />
                <span style={{ color: COLORS.textMuted, fontSize: 10 }}>{bank}</span>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 10, height: 2, background: COLORS.white, borderTop: '1px dashed' }} />
              <span style={{ color: COLORS.textMuted, fontSize: 10 }}>Total</span>
            </div>
          </div>
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
