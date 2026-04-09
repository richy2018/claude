import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getComponentDetail } from '../utils/api';

const HY_RANGES = [
  { label: '1Y', months: 12 }, { label: '2Y', months: 24 },
  { label: '5Y', months: 60 }, { label: 'ALL', months: 0 },
];

export default function CreditSpreadsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hyRange, setHyRange] = useState(24);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getComponentDetail()
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(e => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  const hyHistory = useMemo(() => {
    if (!data?.hy_oas?.history) return [];
    const items = data.hy_oas.history;
    if (hyRange === 0) return items;
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - hyRange);
    const cutoffStr = cutoff.toISOString().slice(0, 10);
    return items.filter(d => d.date >= cutoffStr);
  }, [data, hyRange]);

  if (loading) {
    return <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT, fontSize: 13 }}>Loading credit spread data...</div>;
  }

  if (error) {
    return <div style={{ padding: 16, color: COLORS.red, fontSize: 11, background: '#1a0000', border: `1px solid ${COLORS.red}`, fontFamily: FONT }}>{error}</div>;
  }

  if (!data) return null;

  const hy = data.hy_oas || {};
  const alert = data.alert || {};

  const chgColor = (v) => {
    if (v == null) return COLORS.textDim;
    // For HY OAS: positive = widening (red), negative = compressing (green)
    return v < 0 ? COLORS.green : v > 0 ? COLORS.red : COLORS.textMuted;
  };

  const alertIcon = (level) => {
    if (level === 'LOW') return { emoji: '\u{1F7E2}', color: COLORS.green };
    if (level === 'ELEVATED') return { emoji: '\u{1F7E1}', color: COLORS.amber };
    if (level === 'HIGH') return { emoji: '\u{1F534}', color: COLORS.red };
    return { emoji: '\u26AB', color: COLORS.red };
  };

  const creditIcon = alertIcon(alert.credit?.level);

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Credit Alert */}
      <div style={{
        background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
        padding: '12px 16px', marginBottom: 16,
      }}>
        <div style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1, marginBottom: 8 }}>CREDIT ALERT</div>
        <div style={{ marginBottom: 8 }}>
          <span style={{ fontSize: 11, marginRight: 8 }}>Credit Spreads:</span>
          <span style={{ color: creditIcon.color, fontWeight: 'bold', fontSize: 12 }}>
            {creditIcon.emoji} {alert.credit?.level} STRESS
          </span>
        </div>
        {hy.current != null && (
          <div style={{ fontSize: 10, color: COLORS.textSecondary }}>
            HY OAS at {hy.current}bp — {hy.current > 500 ? 'elevated credit stress' : hy.current > 400 ? 'modestly above normal' : 'contained, no immediate concern'}.
          </div>
        )}
      </div>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1, fontWeight: 'bold' }}>
            CREDIT & SPREADS — HY OAS
          </span>
          {hy.current != null && (
            <span style={{ fontSize: 12, color: hy.current > 500 ? COLORS.red : hy.current > 400 ? COLORS.amber : COLORS.green, fontWeight: 'bold' }}>
              {hy.current} bp
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {HY_RANGES.map(r => (
            <button key={r.label} onClick={() => setHyRange(r.months)} style={{
              padding: '2px 8px', background: hyRange === r.months ? COLORS.amber + '33' : 'none',
              color: hyRange === r.months ? COLORS.amber : COLORS.textDim,
              border: `1px solid ${hyRange === r.months ? COLORS.amber + '44' : COLORS.cardBorder}`,
              fontFamily: FONT, fontSize: 9, cursor: 'pointer',
            }}>{r.label}</button>
          ))}
        </div>
      </div>

      {/* HY OAS Metrics */}
      {hy.current != null && (
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 16,
        }}>
          {[
            { label: 'Current HY OAS', value: `${hy.current} bp`, color: hy.current > 500 ? COLORS.red : hy.current > 400 ? COLORS.amber : COLORS.green },
            { label: '1W Change', value: hy.chg_1w != null ? `${hy.chg_1w > 0 ? '+' : ''}${hy.chg_1w} bp` : '--', color: chgColor(hy.chg_1w) },
            { label: '1M Change', value: hy.chg_1m != null ? `${hy.chg_1m > 0 ? '+' : ''}${hy.chg_1m} bp` : '--', color: chgColor(hy.chg_1m) },
            { label: '3M Change', value: hy.chg_3m != null ? `${hy.chg_3m > 0 ? '+' : ''}${hy.chg_3m} bp` : '--', color: chgColor(hy.chg_3m) },
            { label: '6M Change', value: hy.chg_6m != null ? `${hy.chg_6m > 0 ? '+' : ''}${hy.chg_6m} bp` : '--', color: chgColor(hy.chg_6m) },
            { label: '52W High', value: hy.high_52w != null ? `${hy.high_52w} bp` : '--', color: COLORS.red },
            { label: '52W Low', value: hy.low_52w != null ? `${hy.low_52w} bp` : '--', color: COLORS.green },
            { label: 'Percentile (5Y)', value: hy.percentile_5y != null ? `${hy.percentile_5y}th pct` : '--', color: hy.percentile_5y > 70 ? COLORS.red : hy.percentile_5y > 30 ? COLORS.amber : COLORS.green },
          ].map(m => (
            <div key={m.label} style={{
              background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
              padding: '8px 10px', borderRadius: 2,
            }}>
              <div style={{ color: COLORS.textMuted, fontSize: 8, letterSpacing: 0.5, marginBottom: 3 }}>{m.label}</div>
              <div style={{ color: m.color, fontSize: 14, fontWeight: 'bold' }}>{m.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* HY OAS Chart */}
      {hyHistory.length > 1 && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '8px' }}>
          <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4, paddingLeft: 4 }}>
            HY OAS SPREAD (bp) — BAMLH0A0HYM2
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={hyHistory} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <defs>
                <linearGradient id="hyGradCredit" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COLORS.red} stopOpacity={0.3} />
                  <stop offset="40%" stopColor={COLORS.amber} stopOpacity={0.1} />
                  <stop offset="100%" stopColor={COLORS.green} stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
              <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 9, fontFamily: FONT }}
                tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
              <YAxis tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
                tickFormatter={v => `${v}bp`} domain={['dataMin', 'dataMax']} />
              <Tooltip
                formatter={(v) => [`${v} bp`, 'HY OAS']}
                contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10 }}
                labelStyle={{ color: COLORS.amber }}
              />
              <ReferenceLine y={400} stroke={COLORS.amber} strokeDasharray="6 3" strokeOpacity={0.5}
                label={{ value: '400bp', fill: COLORS.amber, fontSize: 8, position: 'right' }} />
              <ReferenceLine y={500} stroke={COLORS.red} strokeDasharray="6 3" strokeOpacity={0.5}
                label={{ value: '500bp Stress', fill: COLORS.red, fontSize: 8, position: 'right' }} />
              <ReferenceLine y={700} stroke={COLORS.red} strokeDasharray="3 2" strokeOpacity={0.8}
                label={{ value: '700bp Crisis', fill: COLORS.red, fontSize: 8, position: 'right' }} />
              <Area type="monotone" dataKey="value" stroke={COLORS.cyan} fill="url(#hyGradCredit)"
                strokeWidth={2} dot={false} name="HY OAS" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
