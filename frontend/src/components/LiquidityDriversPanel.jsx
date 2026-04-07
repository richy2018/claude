import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, BarChart, Bar, Cell,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliCentralBanks, refreshGli } from '../utils/api';

const CB_COLORS = {
  Fed: COLORS.amber,
  ECB: COLORS.cyan,
  BoJ: COLORS.green,
  PBoC: COLORS.red,
};

const scoreColor = (v) => {
  if (v == null) return COLORS.textMuted;
  if (v > 70) return COLORS.green;
  if (v > 30) return COLORS.amber;
  return COLORS.red;
};

const scoreLabel = (v) => {
  if (v == null) return '--';
  if (v > 70) return 'EXPANSIONARY';
  if (v > 30) return 'NEUTRAL';
  return 'CONTRACTIONARY';
};

// Simple gauge component
function MomentumGauge({ label, score, color }) {
  const pct = score != null ? Math.max(0, Math.min(100, score)) : 0;
  return (
    <div style={{
      background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
      padding: '12px 16px', borderRadius: 2, textAlign: 'center',
    }}>
      <div style={{ color: color || COLORS.white, fontSize: 11, letterSpacing: 1, marginBottom: 8 }}>{label}</div>
      <div style={{ position: 'relative', height: 8, background: '#1a1a1a', borderRadius: 4, overflow: 'hidden', marginBottom: 6 }}>
        <div style={{
          position: 'absolute', left: 0, top: 0, bottom: 0, width: `${pct}%`,
          background: `linear-gradient(90deg, ${COLORS.red}, ${COLORS.amber}, ${COLORS.green})`,
          borderRadius: 4, transition: 'width 0.5s',
        }} />
      </div>
      <div style={{ color: scoreColor(score), fontSize: 18, fontWeight: 'bold' }}>
        {score != null ? score.toFixed(0) : '--'}
      </div>
      <div style={{ color: scoreColor(score), fontSize: 9, letterSpacing: 1, marginTop: 2 }}>
        {scoreLabel(score)}
      </div>
    </div>
  );
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '8px 12px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber, marginBottom: 4 }}>{label}</div>
      {payload.filter(p => p.value != null).map(p => (
        <div key={p.dataKey} style={{ color: p.color || COLORS.white, display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span>{p.name || p.dataKey}</span>
          <span>{p.value?.toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
};

export default function LiquidityDriversPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

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

  // Compute aggregate z-score chart data
  const aggZScoreData = useMemo(() => {
    if (!data?.z_scores) return [];
    // Merge all CBs' z-score series by date
    const dateMap = {};
    const banks = Object.keys(data.z_scores);
    banks.forEach(bank => {
      const zs = data.z_scores[bank]?.z_scores || [];
      zs.forEach(({ date, value }) => {
        if (!dateMap[date]) dateMap[date] = { date };
        dateMap[date][bank] = value;
      });
    });

    // Compute average for aggregate
    const rows = Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date)).map(row => {
      const vals = banks.map(b => row[b]).filter(v => v != null);
      row.aggregate = vals.length > 0 ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
      return row;
    });

    // Compute Howell 65-month sine wave directly in frontend
    // Trough at December 2022 (y=0), peak at ~September 2025 (y=100)
    const TROUGH = new Date('2022-12-01');
    const CYCLE_MONTHS = 65;
    rows.forEach(row => {
      const d = new Date(row.date);
      const monthsFromTrough = (d.getFullYear() - TROUGH.getFullYear()) * 12 + (d.getMonth() - TROUGH.getMonth());
      const wave = Math.sin(2 * Math.PI * monthsFromTrough / CYCLE_MONTHS - Math.PI / 2);
      row.sine = (wave + 1) / 2 * 100; // scale to 0-100
    });

    return rows;
  }, [data]);

  const banks = data?.summary ? Object.keys(data.summary) : [];

  if (loading && !data) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT, fontSize: 13 }}>Loading liquidity drivers...</div>;
  }

  if (error && !data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', fontFamily: FONT, fontSize: 13 }}>
        <div style={{ color: COLORS.red, marginBottom: 12 }}>No CB data cached</div>
        <button onClick={handleRefresh} disabled={refreshing} style={{
          background: COLORS.amber, color: '#000', border: 'none', padding: '8px 20px',
          fontFamily: FONT, fontSize: 12, cursor: 'pointer', letterSpacing: 1,
        }}>
          {refreshing ? 'FETCHING...' : 'FETCH CB DATA'}
        </button>
      </div>
    );
  }

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1 }}>LIQUIDITY DRIVERS — Z-SCORE MOMENTUM</span>
        <button onClick={handleRefresh} disabled={refreshing} style={{
          background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
          padding: '4px 10px', fontFamily: FONT, fontSize: 10, cursor: 'pointer', letterSpacing: 1,
        }}>
          {refreshing ? '...' : 'REFRESH'}
        </button>
      </div>

      {/* Momentum gauges */}
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${banks.length}, 1fr)`, gap: 8, marginBottom: 16 }}>
        {banks.map(bank => (
          <MomentumGauge
            key={bank}
            label={bank}
            score={data?.summary?.[bank]?.momentum_score}
            color={CB_COLORS[bank]}
          />
        ))}
      </div>

      {/* Aggregate z-score chart */}
      {aggZScoreData.length > 0 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px', marginBottom: 12 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8, paddingLeft: 8 }}>
            CB MOMENTUM Z-SCORES (0-100 PERCENTILE)
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={aggZScoreData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
              <XAxis
                dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd"
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
                ticks={[0, 30, 50, 70, 100]}
              />
              <Tooltip content={<CustomTooltip />} />
              {/* Threshold zones */}
              <Area
                type="monotone" dataKey={() => 30} fill={COLORS.red} fillOpacity={0.05}
                stroke="none" baseValue={0}
              />
              {banks.map(bank => (
                <Line
                  key={bank} type="monotone" dataKey={bank}
                  stroke={CB_COLORS[bank] || COLORS.blue} strokeWidth={1} dot={false}
                  strokeOpacity={0.6}
                />
              ))}
              <Line
                type="monotone" dataKey="aggregate" stroke={COLORS.white}
                strokeWidth={2.5} dot={false} name="Aggregate"
              />
              <Line
                type="monotone" dataKey="sine" stroke={COLORS.textDim}
                strokeWidth={1.5} strokeDasharray="6 3" dot={false}
                name="Howell 65-month cycle (fitted)"
              />
            </ComposedChart>
          </ResponsiveContainer>
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 8 }}>
            {banks.map(bank => (
              <div key={bank} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 10, height: 2, background: CB_COLORS[bank] || COLORS.blue }} />
                <span style={{ color: COLORS.textMuted, fontSize: 10 }}>{bank}</span>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 10, height: 3, background: COLORS.white }} />
              <span style={{ color: COLORS.textMuted, fontSize: 10 }}>Aggregate</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 14, height: 0, borderTop: `1.5px dashed ${COLORS.textDim}` }} />
              <span style={{ color: COLORS.textMuted, fontSize: 10 }}>Howell 65-month cycle (fitted)</span>
            </div>
          </div>
        </div>
      )}

      {/* Z-score interpretation guide */}
      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 16px' }}>
        <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8 }}>HOWELL CYCLE INTERPRETATION</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, fontSize: 11 }}>
          <div>
            <span style={{ color: COLORS.red }}>0-30</span>
            <span style={{ color: COLORS.textMuted }}> — Contractionary: CB balance sheets shrinking (QT)</span>
          </div>
          <div>
            <span style={{ color: COLORS.amber }}>30-70</span>
            <span style={{ color: COLORS.textMuted }}> — Neutral: Transition zone, watch for inflection</span>
          </div>
          <div>
            <span style={{ color: COLORS.green }}>70-100</span>
            <span style={{ color: COLORS.textMuted }}> — Expansionary: CB balance sheets growing (QE)</span>
          </div>
        </div>
      </div>

      {data?.updated_at && (
        <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 8, textAlign: 'right' }}>
          Last updated: {new Date(data.updated_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}
