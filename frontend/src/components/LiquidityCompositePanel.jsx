import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliBisCredit, getTickerOverlay, getBacktestSweep, getBacktestDetail, getProductionSignal, runSignalValidation, getSignalValidation } from '../utils/api';

const SIGNAL_LINE_BASE = [
  { key: 'composite_signal', label: 'Composite', color: COLORS.amber, width: 2.5, dash: '' },
  { key: 'quantity_signal', shortLabel: 'Qty', color: COLORS.textDim, width: 1, dash: '4 3' },
  { key: 'rate_signal', shortLabel: 'Rates', color: COLORS.purple, width: 1, dash: '4 3' },
  { key: 'spread_signal', shortLabel: 'Credit', color: COLORS.cyan, width: 1, dash: '4 3' },
  { key: 'curve_signal', shortLabel: 'Curve', color: COLORS.pink, width: 1, dash: '4 3' },
  { key: 'm2_signal', shortLabel: 'M2', color: COLORS.green, width: 1, dash: '4 3' },
  { key: 'dollar_stress_signal', shortLabel: 'Dollar', color: COLORS.orange, width: 1, dash: '4 3' },
];

function getSignalLines(weights) {
  return SIGNAL_LINE_BASE.map(sl => ({
    ...sl,
    label: sl.label || (weights?.[sl.key] != null
      ? `${sl.shortLabel} ${(weights[sl.key] * 100).toFixed(0)}%`
      : sl.shortLabel),
  }));
}

const SIGNAL_LINES = getSignalLines(null);
const QUICK_TICKERS = ['SPY', 'QQQ', 'ACWI', 'EEM', 'AGG', 'HYG'];
const OVERLAY_COLORS = ['#ffff00', '#ffffff', '#ff66ff'];

export default function LiquidityCompositePanel() {
  const [bisData, setBisData] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getGliBisCredit()
      .then(r => { if (!cancelled && r && !r.cached) setBisData(r); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  return (
    <div style={{ fontFamily: FONT }}>
      <ProductionSignalPanel />
      {bisData?.debt_ratio?.ratio_series?.length > 0 && <DebtRatioPanel dr={bisData.debt_ratio} />}
    </div>
  );
}


function ProductionSignalPanel() {
  const [sig, setSig] = useState(null);
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState('4f');

  const load = useCallback(async (m) => {
    setLoading(true);
    try {
      const res = await getProductionSignal(m || model);
      if (res && !res.error && !res.cached) setSig(res);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [model]);

  useEffect(() => { load(); }, []);

  const switchModel = (m) => { setModel(m); load(m); };

  if (loading && !sig) {
    return <div style={{ padding: 20, color: COLORS.textMuted, fontSize: 11 }}>Loading signal...</div>;
  }

  if (!sig) return null;

  const c = sig.current;
  const levelColor = c.level_quintile <= 2 ? COLORS.green : c.level_quintile >= 4 ? COLORS.red : COLORS.amber;
  const momColor = c.mom_quintile <= 2 ? COLORS.green : c.mom_quintile >= 4 ? COLORS.red : COLORS.amber;
  const gaugePct = c.level_percentile;

  return (
    <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '12px', marginTop: 12, fontFamily: FONT }}>
      {/* Header + Model Toggle */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ color: COLORS.amber, fontSize: 13, letterSpacing: 1, fontWeight: 'bold' }}>LIQUIDITY COMPOSITE</span>
          {['4f', '3fb', '2f'].map(m => (
            <button key={m} onClick={() => switchModel(m)} style={{
              padding: '2px 10px', background: model === m ? COLORS.amber + '33' : 'none',
              color: model === m ? COLORS.amber : COLORS.textDim,
              border: `1px solid ${model === m ? COLORS.amber + '44' : COLORS.cardBorder}`,
              fontFamily: FONT, fontSize: 10, cursor: 'pointer',
            }}>{m.toUpperCase()} Model {model === m ? '●' : '○'}</button>
          ))}
        </div>
        <span style={{ color: COLORS.textDim, fontSize: 9 }}>{sig.model_label}</span>
      </div>

      {/* Current Signal Card — DUAL reading */}
      <div style={{ background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, padding: '12px 16px', marginBottom: 12 }}>
        {/* Level reading */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 6 }}>
          <span style={{ color: COLORS.textMuted, fontSize: 10, width: 70 }}>Level:</span>
          <span style={{ color: COLORS.white, fontSize: 20, fontWeight: 'bold' }}>{c.level_value?.toFixed(3)}</span>
          <span style={{ color: COLORS.textMuted, fontSize: 10 }}>{c.level_percentile?.toFixed(0)}th pct</span>
          <span style={{ color: levelColor, fontSize: 12, fontWeight: 'bold' }}>{c.level_label}</span>
        </div>
        {/* Momentum reading */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8 }}>
          <span style={{ color: COLORS.textMuted, fontSize: 10, width: 70 }}>Mom (6M):</span>
          <span style={{ color: COLORS.white, fontSize: 20, fontWeight: 'bold' }}>{c.mom_value?.toFixed(3)}</span>
          <span style={{ color: COLORS.textMuted, fontSize: 10 }}>{c.mom_percentile?.toFixed(0)}th pct</span>
          <span style={{ color: momColor, fontSize: 12, fontWeight: 'bold' }}>{c.mom_label}</span>
        </div>
        {/* Gauge bar (level) */}
        <div style={{ position: 'relative', height: 8, background: '#1a1a1a', borderRadius: 4, overflow: 'hidden', marginBottom: 6 }}>
          <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${gaugePct}%`,
            background: `linear-gradient(90deg, ${COLORS.green}, ${COLORS.amber}, ${COLORS.red})`, borderRadius: 4 }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: COLORS.textDim }}>
          <span>Loose</span><span>Tight</span>
        </div>
        <div style={{ fontSize: 10, marginTop: 6 }}>
          <span style={{ color: levelColor }}>{c.implication}</span>
        </div>
        <div style={{ fontSize: 9, color: COLORS.textDim, marginTop: 4 }}>
          Model: {Object.entries(sig.weights).map(([k,v]) => `${COMP_LABELS[k] || k} ${(v*100).toFixed(0)}%`).join(' + ')}
        </div>
      </div>

      {/* Composite Time Series Chart */}
      {sig.chart?.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
            COMPOSITE LEVEL vs SPY 6M FWD RETURN (both z-scored)
            <span style={{ color: COLORS.textDim, fontSize: 8, marginLeft: 8 }}>Signal reading uses Mom 6M transformation</span>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={sig.chart} margin={{ top: 5, right: 20, bottom: 5, left: 25 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
              <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 9, fontFamily: FONT }} tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
              <YAxis domain={[-3, 3]} tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }} tickFormatter={v => v?.toFixed(1)}
                label={{ value: 'Composite Level', angle: -90, position: 'insideLeft', style: { fill: COLORS.textDim, fontSize: 9 } }} />
              <Tooltip formatter={(v, name) => [typeof v === 'number' ? v.toFixed(3) : v, name]}
                contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10 }} />
              <ReferenceLine y={0} stroke={COLORS.textDim} strokeDasharray="3 3" />
              <Line type="monotone" dataKey="comp_z" stroke={COLORS.amber} strokeWidth={2} dot={false} name="Composite Level" connectNulls />
              <Line type="monotone" dataKey="spy_fwd_z" stroke={COLORS.cyan} strokeWidth={1.5} strokeDasharray="4 2" dot={false} name="SPY 6M fwd (inv)" connectNulls />
              <Line type="monotone" dataKey="roll_corr" stroke={COLORS.textDim} strokeWidth={1} dot={false} name="Roll 36M Corr" connectNulls strokeOpacity={0.4} />
            </ComposedChart>
          </ResponsiveContainer>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', fontSize: 8, color: COLORS.textDim }}>
            <span><span style={{ color: COLORS.amber }}>━</span> Composite Level</span>
            <span><span style={{ color: COLORS.cyan }}>╌</span> SPY 6M fwd (inv)</span>
            <span><span style={{ color: COLORS.textDim }}>─</span> Roll 36M corr</span>
          </div>
        </div>
      )}

      {/* Component Breakdown */}
      {sig.components?.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${sig.components.length}, 1fr)`, gap: 8, marginBottom: 10 }}>
          {sig.components.map(comp => {
            const clr = comp.direction === 'tightening' ? COLORS.red : COLORS.green;
            const trendIcon = comp.trend === 'rising' ? '↑' : comp.trend === 'falling' ? '↓' : '→';
            return (
              <div key={comp.key} style={{ background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, padding: '8px 10px', borderRadius: 2 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1 }}>{comp.label}</span>
                  <span style={{ color: COLORS.textDim, fontSize: 8 }}>{(comp.weight * 100).toFixed(0)}%</span>
                </div>
                <div style={{ color: clr, fontSize: 16, fontWeight: 'bold' }}>
                  {comp.value?.toFixed(2) ?? '--'} <span style={{ fontSize: 12 }}>{trendIcon}</span>
                </div>
                <div style={{ color: clr, fontSize: 8, marginTop: 2 }}>{comp.direction}</div>
              </div>
            );
          })}
        </div>
      )}

      {/* Dominant driver */}
      {sig.dominant_driver && (
        <div style={{ fontSize: 10, color: COLORS.textMuted, marginBottom: 8 }}>
          Dominant driver: <span style={{ color: sig.dominant_driver.direction === 'tightening' ? COLORS.red : COLORS.green, fontWeight: 'bold' }}>
            {sig.dominant_driver.label}</span> ({sig.dominant_driver.direction}, {(sig.dominant_driver.weight * 100).toFixed(0)}% weight)
        </div>
      )}

      {/* Quintile Context */}
      {sig.quintile_context?.length > 0 && (
        <div style={{ background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, padding: '8px 12px', fontSize: 10 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>HISTORICAL CONTEXT (Mom 6M, N=271)</div>
          <table style={{ fontSize: 10, borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                {['Quintile', 'Avg 6M', 'Avg 12M', 'Hit 6M'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Quintile' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 6px', fontSize: 9 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sig.quintile_context.map(qc => (
                <tr key={qc.quintile} style={{
                  borderBottom: `1px solid ${COLORS.cardBorder}22`,
                  background: qc.is_current ? COLORS.amber + '11' : 'none',
                }}>
                  <td style={{ padding: '2px 6px', color: qc.is_current ? COLORS.amber : COLORS.white }}>
                    {qc.quintile} {qc.is_current ? '← current' : ''}
                  </td>
                  <td style={{ padding: '2px 6px', textAlign: 'right', color: qc.avg_6m != null ? (qc.avg_6m > 0 ? COLORS.green : COLORS.red) : COLORS.textDim }}>
                    {qc.avg_6m != null ? `${qc.avg_6m > 0 ? '+' : ''}${qc.avg_6m.toFixed(1)}%` : '--'}
                  </td>
                  <td style={{ padding: '2px 6px', textAlign: 'right', color: qc.avg_12m != null ? (qc.avg_12m > 0 ? COLORS.green : COLORS.red) : COLORS.textDim }}>
                    {qc.avg_12m != null ? `${qc.avg_12m > 0 ? '+' : ''}${qc.avg_12m.toFixed(1)}%` : '--'}
                  </td>
                  <td style={{ padding: '2px 6px', textAlign: 'right', color: COLORS.textMuted }}>
                    {qc.hit_6m != null ? `${qc.hit_6m.toFixed(0)}%` : '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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

      {/* Backtesting section — collapsed by default */}
      <CollapsibleBacktest />

      {/* Signal Validation — collapsed by default */}
      <SignalValidationPanel />
    </div>
  );
}


const COMP_KEYS = ['quantity_signal', 'rate_signal', 'spread_signal', 'curve_signal', 'm2_signal'];
const W_LABELS = { quantity_signal: 'Qty', rate_signal: 'Rates', spread_signal: 'Credit', curve_signal: 'Curve', m2_signal: 'M2' };
const COMP_LABELS = W_LABELS;

function SignalValidationPanel() {
  const [val, setVal] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Try loading cached results on mount
  useEffect(() => {
    getSignalValidation().then(r => { if (r && !r.error) setVal(r); }).catch(() => {});
  }, []);

  const runValidation = async () => {
    setLoading(true);
    try {
      const r = await runSignalValidation('4f');
      if (r && !r.error) setVal(r);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  return (
    <div style={{ marginTop: 12 }}>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '▾' : '▸'} Signal Validation (Monte Carlo, Equity Curve, Bootstrap)
      </button>
      {expanded && (
        <div style={{ padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>SIGNAL VALIDATION</span>
            <button onClick={runValidation} disabled={loading}
              style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              {loading ? 'RUNNING (~10s)...' : val ? 'RE-RUN VALIDATION' : 'RUN VALIDATION'}
            </button>
            {val && <span style={{ color: COLORS.textDim, fontSize: 9 }}>Model: {val.model || '4f'}</span>}
          </div>

          {!val && !loading && (
            <div style={{ color: COLORS.textDim, fontSize: 9 }}>
              Click RUN VALIDATION to compute Monte Carlo permutation test (10,000 shuffles),
              equity curve simulation, and bootstrap confidence intervals. Takes ~10 seconds.
            </div>
          )}

          {val && (
            <>
              {/* Monte Carlo */}
              {val.monte_carlo && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>MONTE CARLO PERMUTATION TEST ({val.monte_carlo.n_permutations?.toLocaleString()} shuffles, N={val.monte_carlo.n_data_points})</div>
                  <div style={{ padding: '8px 12px', background: '#0a0a0a',
                    borderLeft: `3px solid ${val.monte_carlo.p_value < 0.05 ? COLORS.green : COLORS.red}`,
                    fontSize: 11, marginBottom: 6 }}>
                    <div style={{ color: COLORS.white }}>
                      Actual correlation: <span style={{ fontWeight: 'bold' }}>{val.monte_carlo.actual_corr?.toFixed(4)}</span>
                    </div>
                    <div style={{ color: COLORS.white }}>
                      p-value: <span style={{ fontWeight: 'bold', color: val.monte_carlo.p_value < 0.05 ? COLORS.green : COLORS.red }}>
                        {val.monte_carlo.p_value?.toFixed(4)}
                      </span>
                    </div>
                    <div style={{ color: val.monte_carlo.p_value < 0.05 ? COLORS.green : COLORS.red, fontSize: 10, marginTop: 4 }}>
                      {val.monte_carlo_verdict}
                    </div>
                    <div style={{ color: COLORS.textDim, fontSize: 9, marginTop: 2 }}>
                      Signal ranks in {val.monte_carlo.percentile_rank?.toFixed(1)}th percentile of random noise distribution
                      (null mean: {val.monte_carlo.null_mean?.toFixed(4)}, null std: {val.monte_carlo.null_std?.toFixed(4)})
                    </div>
                  </div>

                  {/* Histogram */}
                  {val.monte_carlo.histogram && (
                    <ResponsiveContainer width="100%" height={120}>
                      <ComposedChart data={val.monte_carlo.histogram.counts.map((c, i) => ({
                        bin: ((val.monte_carlo.histogram.edges[i] + val.monte_carlo.histogram.edges[i+1]) / 2).toFixed(3),
                        count: c,
                      }))} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                        <XAxis dataKey="bin" tick={{ fill: COLORS.textDim, fontSize: 8 }} interval={9} />
                        <YAxis tick={{ fill: COLORS.textDim, fontSize: 8 }} />
                        <Area type="monotone" dataKey="count" fill={COLORS.cardBorder} stroke={COLORS.textMuted} strokeWidth={1} />
                        <ReferenceLine x={val.monte_carlo.actual_corr?.toFixed(3)} stroke={COLORS.red} strokeWidth={2}
                          label={{ value: 'Actual', fill: COLORS.red, fontSize: 8, position: 'top' }} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  )}
                </div>
              )}

              {/* Equity Curve */}
              {val.equity_curve?.metrics && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>EQUITY CURVE SIMULATION</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 8 }}>
                    {[['Signal Strategy', 'portfolio', COLORS.amber], ['Buy & Hold', 'buyhold', COLORS.cyan]].map(([label, key, color]) => {
                      const m = val.equity_curve.metrics[key];
                      return (
                        <div key={key} style={{ background: '#0a0a0a', padding: '8px 10px', border: `1px solid ${COLORS.cardBorder}` }}>
                          <div style={{ color, fontSize: 10, letterSpacing: 1, marginBottom: 4 }}>{label}</div>
                          <div style={{ fontSize: 9, color: COLORS.textMuted, lineHeight: 1.8 }}>
                            <div>Total Return: <span style={{ color: COLORS.white }}>{m?.total_return > 0 ? '+' : ''}{m?.total_return?.toFixed(1)}%</span></div>
                            <div>Ann. Return: <span style={{ color: COLORS.white }}>{m?.annualized_return?.toFixed(2)}%</span></div>
                            <div>Ann. Vol: <span style={{ color: COLORS.white }}>{m?.annualized_vol?.toFixed(2)}%</span></div>
                            <div>Sharpe: <span style={{ color: COLORS.white }}>{m?.sharpe?.toFixed(3)}</span></div>
                            <div>Max DD: <span style={{ color: COLORS.red }}>{m?.max_drawdown?.toFixed(1)}%</span></div>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Equity chart */}
                  {val.equity_curve.chart?.length > 0 && (
                    <ResponsiveContainer width="100%" height={220}>
                      <ComposedChart data={val.equity_curve.chart} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                        <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 8 }} tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
                        <YAxis tick={{ fill: COLORS.textMuted, fontSize: 9 }} tickFormatter={v => `${v?.toFixed(1)}x`} />
                        <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10 }} />
                        <Line type="monotone" dataKey="portfolio" stroke={COLORS.amber} strokeWidth={2} dot={false} name="Signal Strategy" />
                        <Line type="monotone" dataKey="buyhold" stroke={COLORS.cyan} strokeWidth={1.5} strokeDasharray="4 2" dot={false} name="Buy & Hold" />
                      </ComposedChart>
                    </ResponsiveContainer>
                  )}
                </div>
              )}

              {/* Bootstrap */}
              {val.bootstrap && (
                <div>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>BOOTSTRAP CONFIDENCE ({val.bootstrap.n_bootstrap?.toLocaleString()} resamples)</div>
                  <div style={{ padding: '8px 12px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, fontSize: 10 }}>
                    <div style={{ color: COLORS.white, marginBottom: 4 }}>
                      Strategy beats buy-and-hold in <span style={{ color: val.bootstrap.outperformance_rate > 0.5 ? COLORS.green : COLORS.red, fontWeight: 'bold' }}>
                        {(val.bootstrap.outperformance_rate * 100).toFixed(0)}%
                      </span> of bootstrap samples
                    </div>
                    <div style={{ color: COLORS.textMuted, marginBottom: 6 }}>
                      Median outperformance: <span style={{ color: COLORS.white }}>{val.bootstrap.outperformance_median_pct > 0 ? '+' : ''}{val.bootstrap.outperformance_median_pct?.toFixed(1)}%</span>
                    </div>
                    <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                          <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 6px' }}>Terminal Value ($100)</th>
                          <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 6px' }}>5th</th>
                          <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 6px' }}>25th</th>
                          <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 6px', fontWeight: 'bold' }}>Median</th>
                          <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 6px' }}>75th</th>
                          <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 6px' }}>95th</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[['Strategy', 'portfolio_percentiles', COLORS.amber], ['Buy & Hold', 'buyhold_percentiles', COLORS.cyan]].map(([label, key, color]) => {
                          const p = val.bootstrap[key];
                          return (
                            <tr key={label} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                              <td style={{ padding: '3px 6px', color }}>{label}</td>
                              {['5th', '25th', '50th', '75th', '95th'].map(pct => (
                                <td key={pct} style={{ padding: '3px 6px', textAlign: 'right', color: COLORS.white, fontWeight: pct === '50th' ? 'bold' : 'normal' }}>
                                  ${(p?.[pct] * 100)?.toFixed(0)}
                                </td>
                              ))}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}


function CollapsibleBacktest() {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={{ marginTop: 12 }}>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '▾' : '▸'} Signal Optimization & Backtesting
      </button>
      {expanded && <BacktestPanel />}
    </div>
  );
}

function BacktestPanel() {
  const [sweep, setSweep] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [showDiag, setShowDiag] = useState(false);
  const [modelKey, setModelKey] = useState('3fa');

  const runSweep = async (mk) => {
    const m = mk ?? modelKey;
    setLoading(true); setDetail(null); setSelectedIdx(0);
    try {
      const res = await getBacktestSweep(m);
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
      const res = await getBacktestDetail(cfg.signal, cfg.filter, modelKey);
      if (res && !res.error) setDetail(res);
    } catch (e) { console.error(e); }
    finally { setDetailLoading(false); }
  };

  const switchModel = (mk) => {
    setModelKey(mk);
    if (sweep) runSweep(mk);
  };

  const sel = sweep?.leaderboard?.[selectedIdx];

  return (
    <div style={{ marginTop: 12, padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>SIGNAL OPTIMIZATION</span>
        {['2f', '3fa', '3fb', '4f', '5f'].map(mk => (
          <button key={mk} onClick={() => switchModel(mk)}
            style={{ padding: '2px 8px', background: modelKey === mk ? COLORS.amber + '33' : 'none',
              color: modelKey === mk ? COLORS.amber : COLORS.textDim,
              border: `1px solid ${modelKey === mk ? COLORS.amber + '44' : COLORS.cardBorder}`,
              fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
            {mk.toUpperCase()}
          </button>
        ))}
        <button onClick={() => runSweep()} disabled={loading}
          style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
            border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
          {loading ? 'SWEEPING...' : sweep ? 'RE-RUN' : 'RUN SWEEP'}
        </button>
        {sweep && <span style={{ color: COLORS.textDim, fontSize: 9 }}>
          {sweep.total_configs} configs | {sweep.component_keys?.map(k => COMP_LABELS[k] || k).join('+')}
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
                  {['#', 'SIGNAL', 'FILTER', 'N', 'FW FIXED', 'OOS 6M', 'CORR 6M', 'CORR 12M', 'SPREAD'].map(h => (
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
                      color: (row.fw_fixed_mean || 0) < -0.10 ? COLORS.green : (row.fw_fixed_mean || 0) < 0 ? COLORS.textMuted : COLORS.red }}>
                      {row.fw_fixed_mean?.toFixed(3) ?? '--'}
                      {row.fw_fixed_std != null && <span style={{ color: COLORS.textDim, fontWeight: 'normal', fontSize: 7 }}> ±{row.fw_fixed_std.toFixed(2)}</span>}
                      {row.fw_fixed_wrong > 0 && <span style={{ color: COLORS.red, fontSize: 7 }}> {row.fw_fixed_wrong}⚠</span>}
                    </td>
                    <td style={{ padding: '3px 4px', textAlign: 'right',
                      color: (row.oos_corr_6m || 0) < -0.10 ? COLORS.green : (row.oos_corr_6m || 0) < 0 ? COLORS.textMuted : COLORS.red }}>
                      {row.oos_corr_6m?.toFixed(3) ?? '--'}
                    </td>
                    {['corr_6m', 'corr_12m'].map(k => (
                      <td key={k} style={{ padding: '3px 4px', textAlign: 'right',
                        color: (row[k] || 0) < 0 ? COLORS.green : COLORS.red }}>
                        {row[k]?.toFixed(3) ?? '--'}
                      </td>
                    ))}
                    <td style={{ padding: '3px 4px', textAlign: 'right',
                      color: (row.spread_6m || 0) > 0 ? COLORS.green : COLORS.red }}>
                      {row.spread_6m != null ? `${row.spread_6m > 0 ? '+' : ''}${row.spread_6m.toFixed(1)}` : '--'}
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
          {/* Walk-Forward Stability: Approach A (re-optimized) vs B (fixed) */}
          {(detail?.stability_a?.length > 0 || detail?.stability_b?.length > 0) && (
            <div style={{ marginBottom: 6 }}>
              {/* Approach A: Re-optimized */}
              {detail.stability_a?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 2 }}>
                    APPROACH A: RE-OPTIMIZED WEIGHTS PER WINDOW (48M train / 24M test)
                  </div>
                  <div style={{ maxHeight: 120, overflowY: 'auto' }}>
                    <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                      <thead><tr>
                        <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 4px' }}>Window</th>
                        {(sweep?.component_keys || COMP_KEYS).map(k => <th key={k} style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 3px' }}>{W_LABELS[k]}</th>)}
                        <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>OOS</th>
                      </tr></thead>
                      <tbody>
                        {detail.stability_a.map((s, i) => (
                          <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                            <td style={{ padding: '2px 4px', color: COLORS.white }}>{s.period}</td>
                            {(sweep?.component_keys || COMP_KEYS).map(k => (
                              <td key={k} style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>
                                {s.weights?.[k] != null ? (s.weights[k] * 100).toFixed(0) + '%' : '--'}
                              </td>
                            ))}
                            <td style={{ padding: '2px 4px', textAlign: 'right', color: (s.oos_corr || 0) < 0 ? COLORS.green : COLORS.red }}>
                              {s.oos_corr?.toFixed(3) ?? '--'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {detail.fw_summary_a && (
                    <div style={{ fontSize: 8, marginTop: 2, color: COLORS.textMuted }}>
                      A: mean={detail.fw_summary_a.mean?.toFixed(3)}, std={detail.fw_summary_a.std?.toFixed(3)}
                      {detail.fw_summary_a.n_positive > 0 && <span style={{ color: COLORS.red }}> ⚠ {detail.fw_summary_a.n_positive}/{detail.fw_summary_a.n_windows} wrong-sign</span>}
                    </div>
                  )}
                </div>
              )}

              {/* Approach B: Fixed weights */}
              {detail.stability_b?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: COLORS.amber, fontSize: 9, letterSpacing: 1, marginBottom: 2 }}>
                    APPROACH B: FIXED WEIGHTS (full-sample optimized, applied to all windows)
                  </div>
                  <div style={{ maxHeight: 120, overflowY: 'auto' }}>
                    <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                      <thead><tr>
                        <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 4px' }}>Window</th>
                        <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>OOS (fixed)</th>
                        <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>OOS (re-opt)</th>
                      </tr></thead>
                      <tbody>
                        {detail.stability_b.map((s, i) => (
                          <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                            <td style={{ padding: '2px 4px', color: COLORS.white }}>{s.period}</td>
                            <td style={{ padding: '2px 4px', textAlign: 'right', fontWeight: 'bold',
                              color: (s.oos_corr || 0) < 0 ? COLORS.green : COLORS.red }}>
                              {s.oos_corr?.toFixed(3) ?? '--'}
                            </td>
                            <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textDim }}>
                              {detail.stability_a?.[i]?.oos_corr?.toFixed(3) ?? '--'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {detail.fw_summary_b && (
                    <div style={{ fontSize: 8, marginTop: 2, color: COLORS.amber }}>
                      B (fixed): mean={detail.fw_summary_b.mean?.toFixed(3)}, std={detail.fw_summary_b.std?.toFixed(3)}
                      {detail.fw_summary_b.n_positive > 0 && <span style={{ color: COLORS.red }}> ⚠ {detail.fw_summary_b.n_positive}/{detail.fw_summary_b.n_windows} wrong-sign</span>}
                      {' | '}
                      {detail.fw_summary_b.mean != null && detail.fw_summary_a?.mean != null && (
                        <span style={{ color: detail.fw_summary_b.mean < detail.fw_summary_a.mean ? COLORS.green : COLORS.red }}>
                          Fixed {detail.fw_summary_b.mean < detail.fw_summary_a.mean ? 'BEATS' : 'trails'} re-optimized
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div style={{ color: COLORS.textDim, fontSize: 8, padding: '4px 0', borderTop: `1px solid ${COLORS.cardBorder}22`, lineHeight: 1.5 }}>
                Fixed weights test whether the signal is robust across different market regimes.
                If fixed weights show consistent negative OOS, the signal is real.
                If only re-optimized weights work, the signal may be partially overfit.
                Prefer the config with best fixed-weight stability.
              </div>
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
