import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, BarChart, Bar, Cell, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliBisCredit, refreshGli, getTickerOverlay, getBacktestSweep, getBacktestDetail } from '../utils/api';

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

      {/* Backtesting section */}
      <BacktestPanel />
    </div>
  );
}


const COMP_KEYS = ['quantity_signal', 'rate_signal', 'spread_signal', 'curve_signal', 'm2_signal'];
const W_LABELS = { quantity_signal: 'Qty', rate_signal: 'Rates', spread_signal: 'Credit', curve_signal: 'Curve', m2_signal: 'M2' };
const COMP_LABELS = W_LABELS;

function BacktestPanel() {
  const [sweep, setSweep] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [showDiag, setShowDiag] = useState(false);
  const [nFactors, setNFactors] = useState(3);

  const runSweep = async (nf) => {
    const factors = nf ?? nFactors;
    setLoading(true); setDetail(null); setSelectedIdx(0);
    try {
      const res = await getBacktestSweep(factors);
      if (res && !res.cached && !res.error) setSweep(res);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const loadDetail = async (idx) => {
    setSelectedIdx(idx);
    if (!sweep?.leaderboard?.[idx]) return;
    const cfg = sweep.leaderboard[idx];
    setDetailLoading(true);
    try {
      const res = await getBacktestDetail(cfg.signal, cfg.filter, nFactors);
      if (res && !res.error) setDetail(res);
    } catch (e) { console.error(e); }
    finally { setDetailLoading(false); }
  };

  const switchFactors = (nf) => {
    setNFactors(nf);
    if (sweep) runSweep(nf);
  };

  const sel = sweep?.leaderboard?.[selectedIdx];

  return (
    <div style={{ marginTop: 12, padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>SIGNAL OPTIMIZATION</span>
        {[3, 5].map(nf => (
          <button key={nf} onClick={() => switchFactors(nf)}
            style={{ padding: '2px 8px', background: nFactors === nf ? COLORS.amber + '33' : 'none',
              color: nFactors === nf ? COLORS.amber : COLORS.textDim,
              border: `1px solid ${nFactors === nf ? COLORS.amber + '44' : COLORS.cardBorder}`,
              fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
            {nf}-FACTOR
          </button>
        ))}
        <button onClick={() => runSweep()} disabled={loading}
          style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
            border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
          {loading ? 'SWEEPING...' : sweep ? 'RE-RUN' : 'RUN SWEEP'}
        </button>
        {sweep && <span style={{ color: COLORS.textDim, fontSize: 9 }}>
          {sweep.total_configs} configs | {sweep.n_factors || nFactors}F | {sweep.component_keys?.map(k => COMP_LABELS[k] || k).join('+')}
        </span>}
      </div>

      {/* Current signal reading */}
      {sweep?.current_reading && (
        <div style={{ padding: '8px 12px', marginBottom: 8, background: '#0a0a0a',
          borderLeft: `3px solid ${sweep.current_reading.quintile <= 2 ? COLORS.green : sweep.current_reading.quintile >= 4 ? COLORS.red : COLORS.amber}`,
          fontSize: 11 }}>
          <span style={{ color: COLORS.amber, letterSpacing: 1, fontSize: 10 }}>CURRENT SIGNAL </span>
          <span style={{ color: COLORS.textMuted, fontSize: 9 }}>({sweep.current_reading.signal_name}, as of {sweep.current_reading.date}): </span>
          <span style={{ color: COLORS.white, fontWeight: 'bold' }}>{sweep.current_reading.value?.toFixed(3)}</span>
          <span style={{ color: COLORS.textMuted }}> | Q{sweep.current_reading.quintile} | {sweep.current_reading.percentile?.toFixed(0)}th pct | </span>
          <span style={{ color: sweep.current_reading.quintile <= 2 ? COLORS.green : sweep.current_reading.quintile >= 4 ? COLORS.red : COLORS.amber }}>
            {sweep.current_reading.implication}
          </span>
        </div>
      )}

      {/* Auto-summary */}
      {sweep?.summary && (
        <div style={{ padding: '6px 10px', marginBottom: 8, background: '#0a0a0a',
          borderLeft: `3px solid ${sweep.summary.includes('USABLE') ? COLORS.green : sweep.summary.includes('WEAK') ? COLORS.amber : COLORS.red}`,
          fontSize: 11, color: COLORS.textSecondary }}>
          {sweep.summary}
        </div>
      )}

      {!sweep && !loading && (
        <div style={{ color: COLORS.textDim, fontSize: 9 }}>
          Runs automated sweep across 8 signal types × 9 regime filters. Ranks by out-of-sample 6M correlation.
          Tests whether liquidity impulse (momentum) outperforms absolute level.
        </div>
      )}

      {/* Leaderboard */}
      {sweep?.leaderboard?.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>LEADERBOARD (ranked by OOS 6M correlation — click row for detail)</div>
          <div style={{ maxHeight: 280, overflowY: 'auto' }}>
            <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
              <thead style={{ position: 'sticky', top: 0, background: COLORS.bgDark }}>
                <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['#', 'SIGNAL', 'FILTER', 'N', 'OOS 6M ± CI', 'CORR 3M', 'CORR 6M', 'CORR 12M', 'SPREAD', 'MONO'].map(h => (
                    <th key={h} style={{ textAlign: h === 'SIGNAL' || h === 'FILTER' ? 'left' : 'right',
                      color: COLORS.textDim, padding: '3px 4px', fontSize: 8 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sweep.leaderboard.slice(0, 20).map((row, i) => (
                  <tr key={i} onClick={() => loadDetail(i)} style={{
                    borderBottom: `1px solid ${COLORS.cardBorder}22`, cursor: 'pointer',
                    background: i === selectedIdx ? COLORS.amber + '11' : 'none',
                  }}>
                    <td style={{ padding: '3px 4px', color: i === 0 ? COLORS.amber : COLORS.textDim }}>{i + 1}</td>
                    <td style={{ padding: '3px 4px', color: COLORS.white }}>{row.signal_name}</td>
                    <td style={{ padding: '3px 4px', color: COLORS.textMuted }}>{row.filter_name}</td>
                    <td style={{ padding: '3px 4px', color: COLORS.textDim, textAlign: 'right' }}>{row.n}</td>
                    <td style={{ padding: '3px 4px', textAlign: 'right', fontWeight: 'bold',
                      color: (row.oos_corr_6m || 0) < -0.10 ? COLORS.green : (row.oos_corr_6m || 0) < 0 ? COLORS.textMuted : COLORS.red }}>
                      {row.oos_corr_6m?.toFixed(3) ?? '--'}
                      {row.ci_95 && <span style={{ color: COLORS.textDim, fontWeight: 'normal', fontSize: 7 }}> ±{row.ci_95.toFixed(2)}</span>}
                      {row.small_quintile && <span title="Quintile sample sizes below 10" style={{ color: COLORS.amber, marginLeft: 2 }}>⚠</span>}
                    </td>
                    {['corr_3m', 'corr_6m', 'corr_12m'].map(k => (
                      <td key={k} style={{ padding: '3px 4px', textAlign: 'right',
                        color: (row[k] || 0) < 0 ? COLORS.green : COLORS.red }}>
                        {row[k]?.toFixed(3) ?? '--'}
                      </td>
                    ))}
                    <td style={{ padding: '3px 4px', textAlign: 'right',
                      color: (row.spread_6m || 0) > 0 ? COLORS.green : COLORS.red }}>
                      {row.spread_6m != null ? `${row.spread_6m > 0 ? '+' : ''}${row.spread_6m.toFixed(1)}` : '--'}
                    </td>
                    <td style={{ padding: '3px 4px', textAlign: 'right', color: COLORS.textDim }}>
                      {row.monotonicity?.toFixed(2) ?? '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Selected config detail */}
      {sel && (
        <div style={{ borderTop: `1px solid ${COLORS.cardBorder}`, paddingTop: 8 }}>
          <div style={{ color: COLORS.amber, fontSize: 10, marginBottom: 6 }}>
            #{selectedIdx + 1}: {sel.signal_name} + {sel.filter_name} (N={sel.n})
            {detailLoading && <span style={{ color: COLORS.textDim, marginLeft: 8 }}>loading detail...</span>}
          </div>

          {/* Quintile returns from sweep */}
          {sel.q_avgs && (
            <div style={{ display: 'flex', gap: 12, marginBottom: 6, fontSize: 10 }}>
              {['Q1', 'Q2', 'Q3', 'Q4', 'Q5'].map((q, i) => (
                <span key={q}>
                  <span style={{ color: COLORS.textDim }}>{q}: </span>
                  <span style={{ color: sel.q_avgs[i] != null ? (sel.q_avgs[i] > 0 ? COLORS.green : COLORS.red) : COLORS.textDim }}>
                    {sel.q_avgs[i] != null ? `${sel.q_avgs[i] > 0 ? '+' : ''}${sel.q_avgs[i].toFixed(1)}%` : '--'}
                  </span>
                </span>
              ))}
            </div>
          )}

          {/* Detail: quintile table with hit rates */}
          {detail?.regime_table && (
            <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%', marginBottom: 6 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['QUINTILE', 'N', '3M', '6M', '12M', 'HIT 3M', 'HIT 6M'].map(h => (
                    <th key={h} style={{ textAlign: h === 'QUINTILE' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 4px', fontSize: 8 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {detail.regime_table.map(row => (
                  <tr key={row.quintile} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                    <td style={{ padding: '2px 4px', color: COLORS.white, fontSize: 9 }}>{row.quintile}</td>
                    <td style={{ padding: '2px 4px', color: COLORS.textDim, textAlign: 'right' }}>{row.count}</td>
                    {['avg_3m', 'avg_6m', 'avg_12m'].map(k => (
                      <td key={k} style={{ padding: '2px 4px', textAlign: 'right',
                        color: row[k] == null ? COLORS.textDim : row[k] > 0 ? COLORS.green : COLORS.red }}>
                        {row[k] != null ? `${row[k] > 0 ? '+' : ''}${row[k].toFixed(1)}%` : '--'}
                      </td>
                    ))}
                    {['hit_3m', 'hit_6m'].map(k => (
                      <td key={k} style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted, fontSize: 8 }}>
                        {row[k] != null ? `${row[k].toFixed(0)}%` : '--'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Optimized weights from detail */}
          {detail?.optimized_weights && (
            <div style={{ fontSize: 9, marginBottom: 6 }}>
              <span style={{ color: COLORS.textMuted }}>Opt weights: </span>
              {Object.entries(detail.optimized_weights).map(([k, v]) => (
                <span key={k} style={{ marginRight: 8 }}>
                  <span style={{ color: COLORS.textDim }}>{W_LABELS[k] || k}</span>
                  <span style={{ color: COLORS.amber, marginLeft: 2 }}>{(v * 100).toFixed(0)}%</span>
                </span>
              ))}
            </div>
          )}

          {/* SPY 6M Forward Overlay — z-score normalized, inverted for co-movement */}
          {detail?.overlay_chart?.length > 0 && (
            <div style={{ marginTop: 8, marginBottom: 8 }}>
              <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>
                SIGNAL (z-score) vs SPY 6M FWD RETURN (z-score, inverted, shifted -6M) — lines should move together
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={detail.overlay_chart} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                  <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 9, fontFamily: FONT }} tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
                  <YAxis domain={[-3, 3]} tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }} tickFormatter={v => v?.toFixed(1)} />
                  <Tooltip
                    formatter={(v, name) => [v?.toFixed(2), name === 'signal_z' ? 'Signal (z)' : name === 'spy_fwd_z' ? 'SPY fwd (z, inv)' : 'Roll Corr']}
                    contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10 }}
                  />
                  <ReferenceLine y={0} stroke={COLORS.textDim} strokeDasharray="3 3" />
                  <Line type="monotone" dataKey="signal_z" stroke={COLORS.amber} strokeWidth={2} dot={false} name="Signal (z)" connectNulls />
                  <Line type="monotone" dataKey="spy_fwd_z" stroke={COLORS.cyan} strokeWidth={1.5} strokeDasharray="4 2" dot={false} name="SPY fwd (z, inv)" connectNulls />
                  <Line type="monotone" dataKey="roll_corr" stroke={COLORS.textDim} strokeWidth={1} dot={false} name="Roll 36M Corr" connectNulls strokeOpacity={0.5} />
                </ComposedChart>
              </ResponsiveContainer>
              <div style={{ display: 'flex', gap: 12, justifyContent: 'center', fontSize: 8, color: COLORS.textDim }}>
                <span><span style={{ color: COLORS.amber }}>━</span> Signal (z-score)</span>
                <span><span style={{ color: COLORS.cyan }}>╌</span> SPY 6M fwd (z-score, inverted)</span>
                <span><span style={{ color: COLORS.textDim }}>─</span> Rolling 36M correlation</span>
              </div>
            </div>
          )}

          {/* Drop Tests — marginal contribution of each component */}
          {detail?.drop_tests?.length > 0 && (
            <div style={{ padding: '6px 10px', marginBottom: 6, background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, fontSize: 10 }}>
              <div style={{ color: COLORS.amber, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>DROP TESTS — marginal contribution of each component</div>
              {detail.drop_tests.map(dt => {
                const isHarmful = dt.oos_corr != null && detail.optimized_weights && (() => {
                  // Compare: is OOS better WITHOUT this component?
                  const fullOos = detail.stability?.[0]?.oos_corr;
                  return fullOos != null && dt.oos_corr < fullOos;
                })();
                return (
                  <div key={dt.dropped} style={{ display: 'flex', gap: 12, fontSize: 10, padding: '1px 0' }}>
                    <span style={{ color: COLORS.textMuted, width: 120 }}>Drop {dt.dropped_label}:</span>
                    <span style={{ color: COLORS.white }}>OOS {dt.oos_corr?.toFixed(3) ?? '--'}</span>
                    <span style={{ color: COLORS.textDim }}>Full {dt.full_corr?.toFixed(3) ?? '--'}</span>
                  </div>
                );
              })}
              <div style={{ color: COLORS.textDim, fontSize: 8, marginTop: 2 }}>
                If dropping a component improves OOS, it's adding noise. If OOS worsens, the component carries signal.
              </div>
            </div>
          )}

          {/* Weight Stability */}
          {detail?.stability?.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>WEIGHT STABILITY (walk-forward 120M train / 60M test)</div>
              <div style={{ maxHeight: 160, overflowY: 'auto' }}>
                <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                  <thead style={{ position: 'sticky', top: 0, background: COLORS.bgDark }}>
                    <tr>
                      <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 4px' }}>Window</th>
                      {COMP_KEYS.map(k => <th key={k} style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>{W_LABELS[k]}</th>)}
                      <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>OOS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.stability.map((s, i) => (
                      <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                        <td style={{ padding: '2px 4px', color: COLORS.white }}>{s.period}</td>
                        {COMP_KEYS.map(k => (
                          <td key={k} style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>
                            {s.weights[k] != null ? (s.weights[k] * 100).toFixed(0) + '%' : '--'}
                          </td>
                        ))}
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: (s.oos_corr || 0) < 0 ? COLORS.green : COLORS.red }}>
                          {s.oos_corr?.toFixed(3) ?? '--'}
                        </td>
                      </tr>
                    ))}
                    {detail.weight_std && Object.keys(detail.weight_std).length > 0 && (
                      <tr style={{ borderTop: `1px solid ${COLORS.cardBorder}` }}>
                        <td style={{ padding: '2px 4px', color: COLORS.amber, fontSize: 8 }}>Std Dev</td>
                        {COMP_KEYS.map(k => (
                          <td key={k} style={{ padding: '2px 4px', textAlign: 'right',
                            color: (detail.weight_std[k] || 0) > 15 ? COLORS.red : COLORS.textDim, fontSize: 8 }}>
                            {detail.weight_std[k] != null ? `±${detail.weight_std[k].toFixed(0)}%` : '--'}
                            {(detail.weight_std[k] || 0) > 15 && ' ⚠'}
                          </td>
                        ))}
                        <td />
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {detail.oos_summary && (
                <div style={{ fontSize: 9, marginTop: 4, color: COLORS.textMuted }}>
                  OOS across windows: mean={detail.oos_summary.mean?.toFixed(3)}, std={detail.oos_summary.std?.toFixed(3)}
                  {detail.oos_summary.n_positive > 0 && (
                    <span style={{ color: COLORS.red, marginLeft: 8 }}>⚠ {detail.oos_summary.n_positive}/{detail.oos_summary.n_windows} windows had wrong-sign (positive) OOS</span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Component diagnostics + drawdowns */}
      {sweep && (
        <>
          <button onClick={() => setShowDiag(!showDiag)} style={{
            background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
            fontFamily: FONT, fontSize: 9, padding: '2px 10px', cursor: 'pointer', width: '100%', textAlign: 'left', marginTop: 6,
          }}>
            {showDiag ? '▾' : '▸'} DIAGNOSTICS (components, marginal contribution, drawdowns)
          </button>
          {showDiag && (
            <div style={{ marginTop: 6 }}>
              {/* Component power */}
              {sweep.component_diagnostics && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>COMPONENT PREDICTIVE POWER (correlation with SPY forward returns)</div>
                  <table style={{ fontSize: 9, borderCollapse: 'collapse' }}>
                    <thead>
                      <tr><th style={{ padding: '2px 6px', color: COLORS.textDim, textAlign: 'left' }}>Component</th>
                        {['3M', '6M', '12M'].map(h => <th key={h} style={{ padding: '2px 8px', color: COLORS.textDim }}>{h}</th>)}
                        <th style={{ padding: '2px 8px', color: COLORS.textDim }}>Marginal</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(sweep.component_diagnostics).map(([k, cd]) => {
                        const mg = sweep.marginal_contribution?.[k];
                        return (
                          <tr key={k}>
                            <td style={{ padding: '2px 6px', color: COLORS.white }}>{W_LABELS[k] || k}</td>
                            {['corr_3m', 'corr_6m', 'corr_12m'].map(h => (
                              <td key={h} style={{ padding: '2px 8px', textAlign: 'center',
                                color: (cd[h] || 0) < -0.05 ? COLORS.green : (cd[h] || 0) > 0.05 ? COLORS.red : COLORS.textDim,
                                background: (cd[h] || 0) < -0.10 ? COLORS.green + '11' : (cd[h] || 0) > 0.10 ? COLORS.red + '11' : 'none' }}>
                                {cd[h]?.toFixed(3) ?? '--'}
                              </td>
                            ))}
                            <td style={{ padding: '2px 8px', textAlign: 'center',
                              color: cd.label === 'SIGNAL CARRIER' ? COLORS.green : cd.label === 'HARMFUL' ? COLORS.red : COLORS.textDim,
                              fontSize: 8 }}>
                              {cd.label === 'HARMFUL' ? '⚠ ' : cd.label === 'SIGNAL CARRIER' ? '✓ ' : ''}{cd.label || (mg?.harmful ? '⚠ HARMFUL' : 'OK')}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Drawdowns */}
              {sweep.drawdown_analysis?.length > 0 && (
                <div>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>DRAWDOWN ANALYSIS (composite signal during major SPY drawdowns)</div>
                  <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        {['PEAK', 'TROUGH', 'DEPTH', 'DRIVER', 'SIG 3M BEFORE', 'SIG AT PEAK', 'SIG AT TROUGH'].map(h => (
                          <th key={h} style={{ padding: '2px 5px', color: COLORS.textDim, fontSize: 8, textAlign: h === 'PEAK' || h === 'TROUGH' || h === 'DRIVER' ? 'left' : 'right' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sweep.drawdown_analysis.map((dd, i) => (
                        <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                          <td style={{ padding: '2px 5px', color: COLORS.white }}>{dd.peak?.slice(0, 7)}</td>
                          <td style={{ padding: '2px 5px', color: COLORS.white }}>{dd.trough?.slice(0, 7)}</td>
                          <td style={{ padding: '2px 5px', color: COLORS.red, textAlign: 'right' }}>{dd.depth?.toFixed(1)}%</td>
                          <td style={{ padding: '2px 5px', color: COLORS.textDim, fontSize: 8 }}>{dd.driver || ''}</td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: (dd.sig_3m_before || 0) > 0 ? COLORS.red : COLORS.green }}>
                            {dd.sig_3m_before?.toFixed(2) ?? '--'}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: (dd.sig_at_peak || 0) > 0 ? COLORS.red : COLORS.green }}>
                            {dd.sig_at_peak?.toFixed(2) ?? '--'}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: (dd.sig_at_trough || 0) < 0 ? COLORS.green : COLORS.textMuted }}>
                            {dd.sig_at_trough?.toFixed(2) ?? '--'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div style={{ color: COLORS.textDim, fontSize: 8, marginTop: 2 }}>Positive signal before peak = tightening correctly detected. Negative at trough = loosening detected.</div>
                  <div style={{ color: COLORS.textMuted, fontSize: 8, marginTop: 4, padding: '4px 8px', background: '#0a0a0a', borderLeft: `2px solid ${COLORS.amber}`, lineHeight: 1.6 }}>
                    NOTE: This signal predicts average 6M forward returns across regimes.
                    It is NOT a crash predictor. Exogenous shocks (COVID) and rapid policy shifts
                    (Q4 2018 autopilot) may not be captured. Use for allocation tilting, not tail risk hedging.
                  </div>
                </div>
              )}

              {/* Transition matrix from detail */}
              {detail?.transition_matrix?.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>QUINTILE TRANSITIONS (% monthly) — {sel?.signal_name}</div>
                  <table style={{ fontSize: 9, borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={{ padding: '2px 6px', color: COLORS.textDim }}>From\To</th>
                        {detail.transition_matrix[0] && Object.keys(detail.transition_matrix[0]).filter(k => k !== 'from').map(k => (
                          <th key={k} style={{ padding: '2px 6px', color: COLORS.textDim }}>{k}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {detail.transition_matrix.map(row => (
                        <tr key={row.from}>
                          <td style={{ padding: '2px 6px', color: COLORS.white }}>{row.from}</td>
                          {Object.entries(row).filter(([k]) => k !== 'from').map(([k, v]) => (
                            <td key={k} style={{ padding: '2px 6px', textAlign: 'right',
                              color: v > 50 ? COLORS.green : v > 20 ? COLORS.textMuted : COLORS.textDim,
                              background: v > 50 ? COLORS.green + '11' : 'none' }}>
                              {v.toFixed(0)}%
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
