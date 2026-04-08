import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, BarChart, Bar, Cell, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliBisCredit, refreshGli, getTickerOverlay } from '../utils/api';

const SIGNAL_LINES = [
  { key: 'composite_signal', label: 'Composite', color: COLORS.amber, width: 2.5, dash: '' },
  { key: 'quantity_signal', label: 'Quantity 25%', color: COLORS.textDim, width: 1, dash: '4 3' },
  { key: 'rate_signal', label: 'Rates 25%', color: COLORS.purple, width: 1, dash: '4 3' },
  { key: 'spread_signal', label: 'Credit 20%', color: COLORS.cyan, width: 1, dash: '4 3' },
  { key: 'curve_signal', label: 'Curve 15%', color: COLORS.pink, width: 1, dash: '4 3' },
  { key: 'm2_signal', label: 'M2 15%', color: COLORS.green, width: 1, dash: '4 3' },
];

const QUICK_TICKERS = ['SPY', 'QQQ', 'ACWI', 'EEM', 'AGG', 'HYG'];
const OVERLAY_COLORS = ['#ffff00', '#ffffff', '#ff66ff'];

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

      {/* Debt/Liquidity Ratio + Composite Signal */}
      {data?.debt_ratio?.ratio_series?.length > 0 && <DebtRatioPanel dr={data.debt_ratio} />}

      {data?.updated_at && (
        <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 8, textAlign: 'right' }}>
          Last updated: {new Date(data.updated_at).toLocaleString()} | BIS data has ~4 month lag
        </div>
      )}
    </div>
  );
}


function DebtRatioPanel({ dr }) {
  const [visibleLines, setVisibleLines] = useState(new Set(['composite_signal']));
  const [overlays, setOverlays] = useState([]); // [{ticker, points, zscore_points, color}]
  const [tickerInput, setTickerInput] = useState('');
  const [overlayLoading, setOverlayLoading] = useState(false);
  const [overlayMode, setOverlayMode] = useState('zscore'); // 'zscore' or 'raw'
  const transitions = dr.transitions || [];

  const toggleLine = (key) => {
    setVisibleLines(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleOverlay = useCallback(async (ticker) => {
    // If already active, remove it
    if (overlays.some(o => o.ticker === ticker)) {
      setOverlays(prev => prev.filter(o => o.ticker !== ticker));
      return;
    }
    // Otherwise add (max 3)
    if (overlays.length >= 3) return;
    setOverlayLoading(true);
    try {
      const res = await getTickerOverlay(ticker);
      if (res?.points?.length > 0) {
        const color = OVERLAY_COLORS[overlays.length % OVERLAY_COLORS.length];
        setOverlays(prev => [...prev, { ticker, points: res.points, zscore_points: res.zscore_points || [], color }]);
      }
    } catch (e) {
      console.error(`Failed to load ${ticker}:`, e);
    } finally {
      setOverlayLoading(false);
    }
  }, [overlays]);

  // Merge overlay data into signal chart data
  const signalData = useMemo(() => {
    const filtered = dr.ratio_series.filter(d => d.composite_signal != null);
    if (overlays.length === 0) return filtered;
    return filtered.map(d => {
      const row = { ...d };
      overlays.forEach(ov => {
        if (overlayMode === 'zscore') {
          const zpt = ov.zscore_points?.find(p => p.date === d.date);
          if (zpt) row[`ov_${ov.ticker}`] = zpt.zscore;
        } else {
          const pt = ov.points.find(p => p.date === d.date);
          if (pt) row[`ov_${ov.ticker}`] = pt.price;
        }
      });
      return row;
    });
  }, [dr.ratio_series, overlays, overlayMode]);

  // Compute correlation between composite and overlay returns
  const correlations = useMemo(() => {
    if (overlays.length === 0) return {};
    const corrs = {};
    const compVals = signalData.map(d => d.composite_signal).filter(v => v != null);
    overlays.forEach(ov => {
      const prices = signalData.map(d => d[`ov_${ov.ticker}`]).filter(v => v != null);
      if (prices.length < 36) return;
      // Compute returns
      const returns = prices.slice(1).map((p, i) => (p - prices[i]) / prices[i]);
      const compSlice = compVals.slice(compVals.length - returns.length);
      if (compSlice.length !== returns.length || returns.length < 12) return;
      // Pearson correlation
      const n = returns.length;
      const meanR = returns.reduce((s, v) => s + v, 0) / n;
      const meanC = compSlice.reduce((s, v) => s + v, 0) / n;
      let num = 0, denR = 0, denC = 0;
      for (let i = 0; i < n; i++) {
        const dr2 = returns[i] - meanR, dc = compSlice[i] - meanC;
        num += dr2 * dc; denR += dr2 * dr2; denC += dc * dc;
      }
      const corr = denR > 0 && denC > 0 ? num / Math.sqrt(denR * denC) : 0;
      corrs[ov.ticker] = corr;
    });
    return corrs;
  }, [signalData, overlays]);

  return (
    <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 8px', marginTop: 12 }}>
      {/* Interpretation summary */}
      {dr.interpretation && (
        <div style={{ padding: '8px 12px', marginBottom: 8, background: COLORS.bgDark, borderLeft: `3px solid ${dr.composite_signal === 'tightening' ? COLORS.red : COLORS.green}`, fontSize: 11, color: COLORS.textSecondary, lineHeight: 1.6 }}>
          {dr.interpretation}
        </div>
      )}

      {/* Overlay controls */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1 }}>OVERLAY:</span>
        {QUICK_TICKERS.map(t => {
          const active = overlays.some(o => o.ticker === t);
          return (
            <button key={t} onClick={() => toggleOverlay(t)} disabled={overlayLoading && !active}
              style={{ padding: '2px 8px', background: active ? COLORS.amber + '33' : 'none',
                color: active ? COLORS.amber : COLORS.textMuted,
                border: `1px solid ${active ? COLORS.amber + '66' : COLORS.cardBorder}`,
                fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
              {t}{active ? ' ×' : ''}
            </button>
          );
        })}
        <input value={tickerInput} onChange={e => setTickerInput(e.target.value.toUpperCase())}
          onKeyDown={e => { if (e.key === 'Enter' && tickerInput) { toggleOverlay(tickerInput); setTickerInput(''); } }}
          placeholder="Ticker..." style={{ width: 70, padding: '2px 6px', background: COLORS.bgDark,
            border: `1px solid ${COLORS.cardBorder}`, color: COLORS.white, fontFamily: FONT, fontSize: 9 }} />
        {overlays.length > 0 && (
          <>
            <span style={{ color: COLORS.textDim, fontSize: 9 }}>|</span>
            {['zscore', 'raw'].map(m => (
              <button key={m} onClick={() => setOverlayMode(m)}
                style={{ padding: '2px 6px', background: overlayMode === m ? COLORS.cyan + '33' : 'none',
                  color: overlayMode === m ? COLORS.cyan : COLORS.textDim,
                  border: `1px solid ${overlayMode === m ? COLORS.cyan + '44' : COLORS.cardBorder}`,
                  fontFamily: FONT, fontSize: 8, cursor: 'pointer' }}>
                {m === 'zscore' ? 'Z-SCORE' : 'RAW PRICE'}
              </button>
            ))}
          </>
        )}
        {overlayLoading && <span style={{ color: COLORS.textDim, fontSize: 9 }}>loading...</span>}
      </div>

      {/* Ratio chart */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingLeft: 8, marginBottom: 4 }}>
        <span style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1 }}>DEBT / LIQUIDITY RATIO (ALL SECTOR / PRIVATE NF)</span>
        <span style={{ color: dr.zone === 'crisis' ? COLORS.red : dr.zone === 'stress' ? COLORS.amber : COLORS.green, fontSize: 14 }}>
          {dr.current_ratio?.toFixed(2)}x <span style={{ fontSize: 10 }}>({dr.zone?.toUpperCase()})</span>
        </span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={dr.ratio_series} margin={{ top: 5, right: 50, bottom: 5, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
          <XAxis dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
          <YAxis yAxisId="left" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} domain={['dataMin', 'dataMax']} tickFormatter={v => `${v?.toFixed(1)}x`} />
          <Tooltip formatter={(v) => typeof v === 'number' ? v.toFixed(3) : v} labelStyle={{ color: COLORS.amber, fontFamily: FONT }}
            contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 11 }} />
          <ReferenceLine yAxisId="left" y={2.0} stroke={COLORS.amber} strokeDasharray="6 3" label={{ value: 'Stress 2.0x', fill: COLORS.amber, fontSize: 9, position: 'right' }} />
          <ReferenceLine yAxisId="left" y={2.3} stroke={COLORS.red} strokeDasharray="6 3" label={{ value: 'Crisis 2.3x', fill: COLORS.red, fontSize: 9, position: 'right' }} />
          {transitions.slice(-20).map((t, i) => (
            <ReferenceLine key={i} yAxisId="left" x={t.date} stroke={t.direction === 'T' ? COLORS.red : COLORS.green} strokeDasharray="4 2" strokeOpacity={0.5}
              label={{ value: t.direction, fill: t.direction === 'T' ? COLORS.red : COLORS.green, fontSize: 8, position: 'top' }} />
          ))}
          <Line yAxisId="left" type="monotone" dataKey="ratio" stroke={COLORS.white} strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Composite Signal chart */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingLeft: 8, marginTop: 16, marginBottom: 4 }}>
        <span style={{ color: COLORS.textMuted, fontSize: 10, letterSpacing: 1 }}>COMPOSITE TIGHTENING (25% Qty + 25% Rates + 20% Credit + 15% Curve + 15% M2)</span>
        {dr.current_composite != null && (
          <span style={{ color: dr.composite_signal === 'tightening' ? COLORS.red : COLORS.green, fontSize: 12 }}>
            {dr.current_composite > 0 ? '+' : ''}{dr.current_composite.toFixed(2)}
            <span style={{ fontSize: 10, marginLeft: 4 }}>({dr.composite_signal?.toUpperCase()})</span>
            {dr.composite_percentile != null && (
              <span style={{ color: COLORS.textMuted, fontSize: 10, marginLeft: 6 }}>| {dr.composite_percentile.toFixed(0)}th pct</span>
            )}
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={signalData} margin={{ top: 5, right: overlays.length > 0 ? 50 : 20, bottom: 5, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
          <XAxis dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
          <YAxis yAxisId="left" domain={[-1, 1]} tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} tickFormatter={v => v?.toFixed(1)} />
          {overlays.length > 0 && overlayMode === 'raw' && (
            <YAxis yAxisId="right" orientation="right" tick={{ fill: COLORS.textDim, fontSize: 9, fontFamily: FONT }}
              tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}k` : v?.toFixed(0)} />
          )}
          <Tooltip
            formatter={(v, name) => {
              const labels = { quantity_signal: 'Quantity 25%', rate_signal: 'Rates 25%', spread_signal: 'Credit 20%', curve_signal: 'Curve 15%', m2_signal: 'M2 15%', composite_signal: 'Composite' };
              if (name.startsWith('ov_')) return [v?.toFixed(1), name.replace('ov_', '')];
              return [v?.toFixed(3), labels[name] || name];
            }}
            labelStyle={{ color: COLORS.amber, fontFamily: FONT }}
            contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 11 }}
          />
          <ReferenceLine yAxisId="left" y={0} stroke={COLORS.textDim} strokeWidth={1} />
          {visibleLines.has('composite_signal') && (
            <Area yAxisId="left" type="monotone" dataKey="composite_signal" dot={false} stroke="none" fillOpacity={0.2} fill="url(#compositeGradient)" />
          )}
          {SIGNAL_LINES.map(sl =>
            visibleLines.has(sl.key) && (
              <Line key={sl.key} yAxisId="left" type="monotone" dataKey={sl.key}
                stroke={sl.color} strokeWidth={sl.width} strokeDasharray={sl.dash}
                dot={false} strokeOpacity={sl.key === 'composite_signal' ? 1 : 0.6} />
            )
          )}
          {overlays.map(ov => (
            <Line key={ov.ticker} yAxisId={overlayMode === 'raw' ? 'right' : 'left'} type="monotone" dataKey={`ov_${ov.ticker}`}
              stroke={ov.color} strokeWidth={1.5} strokeDasharray="6 2" dot={false} connectNulls
              strokeOpacity={0.8} />
          ))}
          <defs>
            <linearGradient id="compositeGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COLORS.red} stopOpacity={0.7} />
              <stop offset="50%" stopColor={COLORS.red} stopOpacity={0.02} />
              <stop offset="50%" stopColor={COLORS.green} stopOpacity={0.02} />
              <stop offset="100%" stopColor={COLORS.green} stopOpacity={0.7} />
            </linearGradient>
          </defs>
        </ComposedChart>
      </ResponsiveContainer>

      {/* Interactive legend */}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 6, flexWrap: 'wrap' }}>
        {SIGNAL_LINES.map(sl => (
          <div key={sl.key} onClick={() => toggleLine(sl.key)}
            style={{ display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer',
              opacity: visibleLines.has(sl.key) ? 1 : 0.3, userSelect: 'none' }}>
            <div style={{ width: 12, height: 0, borderTop: `${sl.key === 'composite_signal' ? '2.5' : '1.5'}px ${sl.dash ? 'dashed' : 'solid'} ${sl.color}` }} />
            <span style={{ color: COLORS.textMuted, fontSize: 8 }}>{sl.label}</span>
          </div>
        ))}
      </div>

      {/* Correlation readouts */}
      {Object.keys(correlations).length > 0 && (
        <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 6 }}>
          {Object.entries(correlations).map(([ticker, corr]) => (
            <span key={ticker} style={{ fontSize: 10, color: COLORS.textMuted }}>
              <span style={{ color: overlays.find(o => o.ticker === ticker)?.color || COLORS.white }}>{ticker}</span>
              {' '}correlation with composite: <span style={{ color: corr < 0 ? COLORS.green : COLORS.red }}>{corr.toFixed(2)}</span>
              {' '}(full period)
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
