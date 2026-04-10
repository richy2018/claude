import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getGliBisCredit, getTickerOverlay, getBacktestSweep, getBacktestDetail, getProductionSignal, runSignalValidation, getSignalValidation, runRegimeAnalysis, getRegimeAnalysis, runImprovements, getImprovements, runDefensiveStudy, getDefensiveStudy, refreshData, clearCache } from '../utils/api';
import { BarChart, Bar } from 'recharts';

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
  const [model, setModel] = useState('5f');

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
      {/* Header with refresh */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ color: COLORS.amber, fontSize: 15, letterSpacing: 1, fontWeight: 'bold' }}>GLI PRODUCTION SIGNAL</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ color: COLORS.textDim, fontSize: 8 }}>
            5F Combined · Refreshed: {sig.last_refreshed || c.date}
          </span>
          <button onClick={async () => { clearCache(); await refreshData(); load(); }}
            style={{ padding: '2px 8px', background: 'none', color: COLORS.cyan,
              border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 8, cursor: 'pointer' }}>
            ↻ REFRESH
          </button>
        </div>
      </div>

      {/* HERO Signal Card */}
      <div style={{ background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, padding: '16px 20px', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Quintile + Allocation — the big numbers */}
          <div style={{ textAlign: 'center', minWidth: 120 }}>
            <div style={{ color: levelColor, fontSize: 36, fontWeight: 'bold', lineHeight: 1 }}>Q{c.level_quintile}</div>
            <div style={{ color: levelColor, fontSize: 11, fontWeight: 'bold', marginTop: 2 }}>{c.level_label}</div>
          </div>
          <div style={{ textAlign: 'center', minWidth: 140 }}>
            <div style={{ color: c.level_quintile <= 3 ? COLORS.green : COLORS.red, fontSize: 28, fontWeight: 'bold', lineHeight: 1 }}>
              {c.level_quintile <= 3 ? '100%' : '10%'}
            </div>
            <div style={{ color: COLORS.textMuted, fontSize: 10, marginTop: 2 }}>EQUITY ALLOCATION</div>
          </div>
          {/* Signal values */}
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ display: 'flex', gap: 20, marginBottom: 6 }}>
              <div>
                <div style={{ color: COLORS.textDim, fontSize: 8 }}>LEVEL</div>
                <div style={{ color: COLORS.white, fontSize: 16, fontWeight: 'bold' }}>{c.level_value?.toFixed(3)}</div>
                <div style={{ color: COLORS.textDim, fontSize: 8 }}>{c.level_percentile?.toFixed(0)}th pct</div>
              </div>
              <div>
                <div style={{ color: COLORS.textDim, fontSize: 8 }}>MOM (1M)</div>
                <div style={{ color: COLORS.white, fontSize: 16, fontWeight: 'bold' }}>{c.mom_value?.toFixed(3)}</div>
                <div style={{ color: momColor, fontSize: 8 }}>{c.mom_label}</div>
              </div>
              <div>
                <div style={{ color: COLORS.textDim, fontSize: 8 }}>REGIME</div>
                <div style={{ color: c.level_quintile <= 2 ? COLORS.green : c.level_quintile >= 4 ? COLORS.red : COLORS.amber,
                  fontSize: 14, fontWeight: 'bold' }}>
                  {c.level_quintile <= 2 ? 'BULLISH' : c.level_quintile >= 4 ? 'BEARISH' : 'NEUTRAL'}
                </div>
              </div>
            </div>
            {/* Gauge */}
            <div style={{ position: 'relative', height: 6, background: '#1a1a1a', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${gaugePct}%`,
                background: `linear-gradient(90deg, ${COLORS.green}, ${COLORS.amber}, ${COLORS.red})`, borderRadius: 3 }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 7, color: COLORS.textDim, marginTop: 2 }}>
              <span>Loose</span><span>Tight</span>
            </div>
          </div>
        </div>
        <div style={{ fontSize: 10, marginTop: 8, color: levelColor }}>{c.implication}</div>
      </div>

      {/* Five Factor Readings + Consensus */}
      {sig.components?.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <span style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1 }}>FACTOR READINGS</span>
            <span style={{ color: COLORS.amber, fontSize: 10 }}>
              {sig.components.filter(comp => comp.direction === 'loosening').length}/{sig.components.length} factors supportive
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(sig.components.length, 5)}, 1fr)`, gap: 8 }}>
            {sig.components.map(comp => (
              <div key={comp.key} style={{ background: '#0a0a0a', padding: '6px 8px', border: `1px solid ${COLORS.cardBorder}`,
                borderLeft: `3px solid ${comp.direction === 'loosening' ? COLORS.green : COLORS.red}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: COLORS.textMuted, fontSize: 8, letterSpacing: 0.5 }}>{comp.label}</span>
                  <span style={{ color: COLORS.amber, fontSize: 7 }}>{comp.weight ? `${(comp.weight * 100).toFixed(0)}%` : ''}</span>
                </div>
                <div style={{ color: COLORS.white, fontSize: 14, fontWeight: 'bold' }}>{comp.value?.toFixed(2)}</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 8, color: comp.trend === 'rising' ? COLORS.red : comp.trend === 'falling' ? COLORS.green : COLORS.textDim }}>
                    {comp.trend === 'rising' ? '↑ tightening' : comp.trend === 'falling' ? '↓ loosening' : '→ flat'}
                  </span>
                  <span style={{ fontSize: 7, color: COLORS.textDim }}>{comp.as_of ? `as of ${comp.as_of.slice(5)}` : ''}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Composite Signal Chart */}
      {sig.chart?.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
            COMPOSITE SIGNAL vs SPY FORWARD RETURN (z-scored)
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

      {/* Tail Event Track Record — compact */}
      <div style={{ marginTop: 12, marginBottom: 8 }}>
        <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>TAIL EVENT TRACK RECORD — 4/4 detected</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
          {[
            { name: 'GFC 2008', spx: '-57%', strat: 'Detected', ok: true },
            { name: 'COVID 2020', spx: '-34%', strat: 'Detected', ok: true },
            { name: 'Rate Shock 2022', spx: '-25%', strat: 'Detected', ok: true },
            { name: 'Vol Shock 2018', spx: '-20%', strat: 'Detected', ok: true },
          ].map(e => (
            <div key={e.name} style={{ background: '#0a0a0a', padding: '4px 8px', border: `1px solid ${COLORS.cardBorder}`,
              borderLeft: `3px solid ${e.ok ? COLORS.green : COLORS.red}` }}>
              <div style={{ color: COLORS.white, fontSize: 9 }}>{e.name}</div>
              <div style={{ color: COLORS.red, fontSize: 8 }}>SPX: {e.spx}</div>
              <div style={{ color: COLORS.green, fontSize: 8 }}>{e.strat}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Research Archive — collapsed */}
      <div style={{ marginTop: 16 }}>
        <ResearchArchive />
      </div>
    </div>
  );
}


function ResearchArchive() {
  const [expanded, setExpanded] = useState(false);
  return (
    <div>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textDim,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '▾' : '▸'} Research Archive (Signal Validation, Model Improvements, Backtesting)
      </button>
      {expanded && (
        <div style={{ marginTop: 8 }}>
          <CollapsibleBacktest />
          <SignalValidationPanel />
          <ImprovementsPanel />
        </div>
      )}
    </div>
  );
}

const COMP_KEYS = ['quantity_signal', 'rate_signal', 'spread_signal', 'curve_signal', 'm2_signal'];
const W_LABELS = { quantity_signal: 'Qty', rate_signal: 'Rates', spread_signal: 'Credit', curve_signal: 'Curve', m2_signal: 'M2', dollar_stress_signal: 'Dollar' };
const COMP_LABELS = W_LABELS;

function SignalValidationPanel() {
  const [allData, setAllData] = useState(null); // {models: {4f: ..., 3fa: ...}, model_summary: [...]}
  const [selModel, setSelModel] = useState('5f');
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Try loading cached results on mount
  useEffect(() => {
    getSignalValidation().then(r => { if (r && !r.error && r.models) setAllData(r); }).catch(() => {});
  }, []);

  const val = allData?.models?.[selModel] || null;

  const runValidation = async () => {
    setLoading(true);
    try {
      const r = await runSignalValidation('all');
      if (r && !r.error && r.models) setAllData(r);
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>SIGNAL VALIDATION</span>
            <button onClick={runValidation} disabled={loading}
              style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              {loading ? 'RUNNING ALL MODELS (~30s)...' : allData ? 'RE-RUN ALL' : 'RUN VALIDATION (ALL MODELS)'}
            </button>
            {allData && (
              <>
                <span style={{ color: COLORS.textDim, fontSize: 9 }}>Model:</span>
                {['3fa_eq', '3fa', '5f', '4f', '3fb', '2f'].map(m => (
                  <button key={m} onClick={() => setSelModel(m)} disabled={!allData?.models?.[m]}
                    style={{ padding: '2px 8px', background: selModel === m ? COLORS.amber + '33' : 'none',
                      color: selModel === m ? COLORS.amber : allData?.models?.[m] ? COLORS.textMuted : COLORS.textDim,
                      border: `1px solid ${selModel === m ? COLORS.amber + '44' : COLORS.cardBorder}`,
                      fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
                    {m.toUpperCase()}
                  </button>
                ))}
              </>
            )}
          </div>

          {/* Model Comparison Summary */}
          {allData?.model_summary?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>MODEL COMPARISON</div>
              <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {['Model', 'MC Corr', 'p-value', 'Sharpe', 'Sortino', 'MaxDD', 'Sharpe(VS)', 'Sortino(VS)', 'MaxDD(VS)', 'Boot Win%'].map(h => (
                      <th key={h} style={{ textAlign: h === 'Model' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 5px', fontSize: 8 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {allData.model_summary.map(row => {
                    const best = allData.model_summary.reduce((a, b) => (a.p_value || 1) < (b.p_value || 1) ? a : b);
                    const isBest = row.model === best.model;
                    return (
                      <tr key={row.model} onClick={() => setSelModel(row.model)} style={{
                        borderBottom: `1px solid ${COLORS.cardBorder}22`, cursor: 'pointer',
                        background: row.model === selModel ? COLORS.amber + '11' : isBest ? COLORS.green + '08' : 'none',
                      }}>
                        <td style={{ padding: '2px 5px', color: isBest ? COLORS.green : COLORS.white, fontWeight: isBest ? 'bold' : 'normal' }}>{row.model.toUpperCase()}{isBest ? ' ★' : ''}</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', color: (row.mc_corr || 0) < 0 ? COLORS.green : COLORS.red }}>{row.mc_corr?.toFixed(4) ?? '--'}</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', fontWeight: 'bold', color: (row.p_value || 1) < 0.05 ? COLORS.green : COLORS.red }}>{row.p_value?.toFixed(4) ?? '--'}</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.white }}>{row.sharpe_agg?.toFixed(3) ?? '--'}</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.textMuted }}>{row.sortino_agg?.toFixed(3) ?? '--'}</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.red }}>{row.max_dd_agg?.toFixed(1) ?? '--'}%</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.green, fontWeight: 'bold' }}>{row.sharpe_vol_scaled?.toFixed(3) ?? '--'}</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.green }}>{row.sortino_vol_scaled?.toFixed(3) ?? '--'}</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.green }}>{row.max_dd_vol_scaled?.toFixed(1) ?? '--'}%</td>
                        <td style={{ padding: '2px 5px', textAlign: 'right', color: (row.bootstrap_win || 0) > 0.5 ? COLORS.green : COLORS.red }}>{row.bootstrap_win != null ? `${(row.bootstrap_win * 100).toFixed(0)}%` : '--'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {!allData && !loading && (
            <div style={{ color: COLORS.textDim, fontSize: 9 }}>
              Click RUN VALIDATION to compute Monte Carlo, equity curve, and bootstrap for all 4 models (4F, 3FA, 3FB, 2F). Takes ~30 seconds.
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
                  <div style={{ display: 'grid', gridTemplateColumns: val.equity_curve_vol_scaled?.metrics ? '1fr 1fr 1fr' : '1fr 1fr', gap: 12, marginBottom: 8 }}>
                    {[
                      ['Signal Strategy', 'portfolio', COLORS.amber, val.equity_curve.metrics],
                      ['Buy & Hold', 'buyhold', COLORS.cyan, val.equity_curve.metrics],
                      ...(val.equity_curve_vol_scaled?.metrics ? [['Vol-Scaled (10%)', 'portfolio', COLORS.green, val.equity_curve_vol_scaled.metrics]] : []),
                    ].map(([label, key, color, src]) => {
                      const m = src?.[key];
                      return m ? (
                        <div key={label} style={{ background: '#0a0a0a', padding: '8px 10px', border: `1px solid ${COLORS.cardBorder}` }}>
                          <div style={{ color, fontSize: 10, letterSpacing: 1, marginBottom: 4 }}>{label}</div>
                          <div style={{ fontSize: 9, color: COLORS.textMuted, lineHeight: 1.8 }}>
                            <div>Total Return: <span style={{ color: COLORS.white }}>{m?.total_return > 0 ? '+' : ''}{m?.total_return?.toFixed(1)}%</span></div>
                            <div>Ann. Return: <span style={{ color: COLORS.white }}>{m?.annualized_return?.toFixed(2)}%</span></div>
                            <div>Ann. Vol: <span style={{ color: COLORS.white }}>{m?.annualized_vol?.toFixed(2)}%</span></div>
                            <div>Sharpe: <span style={{ color: COLORS.white, fontWeight: label.includes('Vol') ? 'bold' : 'normal' }}>{m?.sharpe?.toFixed(3)}</span></div>
                            <div>Max DD: <span style={{ color: COLORS.red }}>{m?.max_drawdown?.toFixed(1)}%</span></div>
                            {m?.calmar != null && <div>Calmar: <span style={{ color: COLORS.white }}>{m?.calmar?.toFixed(2)}</span></div>}
                          </div>
                        </div>
                      ) : null;
                    })}
                  </div>

                  {/* Equity chart — merge vol-scaled data as third line */}
                  {val.equity_curve.chart?.length > 0 && (() => {
                    const vsChart = val.equity_curve_vol_scaled?.chart;
                    const vsMap = {};
                    if (vsChart) vsChart.forEach(p => { vsMap[p.date] = p.portfolio; });
                    const merged = val.equity_curve.chart.map(p => ({
                      ...p,
                      ...(vsMap[p.date] != null ? { vol_scaled: vsMap[p.date] } : {}),
                    }));
                    return (
                      <ResponsiveContainer width="100%" height={220}>
                        <ComposedChart data={merged} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                          <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 8 }} tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
                          <YAxis tick={{ fill: COLORS.textMuted, fontSize: 9 }} tickFormatter={v => `${v?.toFixed(1)}x`} />
                          <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10 }} />
                          <Line type="monotone" dataKey="portfolio" stroke={COLORS.amber} strokeWidth={2} dot={false} name="Signal Strategy" />
                          <Line type="monotone" dataKey="buyhold" stroke={COLORS.cyan} strokeWidth={1.5} strokeDasharray="4 2" dot={false} name="Buy & Hold" />
                          {merged.some(p => p.vol_scaled != null) && (
                            <Line type="monotone" dataKey="vol_scaled" stroke={COLORS.green} strokeWidth={2} dot={false} name="Vol-Scaled (10%)" connectNulls />
                          )}
                        </ComposedChart>
                      </ResponsiveContainer>
                    );
                  })()}
                  <div style={{ display: 'flex', gap: 12, justifyContent: 'center', fontSize: 8, color: COLORS.textDim, marginTop: 2 }}>
                    <span><span style={{ color: COLORS.amber }}>━</span> Strategy</span>
                    <span><span style={{ color: COLORS.cyan }}>╌</span> Buy & Hold</span>
                    {val.equity_curve_vol_scaled && <span><span style={{ color: COLORS.green }}>━</span> Vol-Scaled (10% target)</span>}
                  </div>
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

              {/* Allocation Rule Comparison */}
              {val.allocation_comparison?.comparison?.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>ALLOCATION RULE COMPARISON</div>
                  <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                    <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                      <thead style={{ position: 'sticky', top: 0, background: COLORS.bgDark }}>
                        <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                          {['Rule', 'Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Total Ret', 'Ann Ret', 'Sharpe', 'Max DD'].map(h => (
                            <th key={h} style={{ textAlign: h === 'Rule' ? 'left' : 'right', color: COLORS.textDim, padding: '3px 5px', fontSize: 8 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {val.allocation_comparison.comparison.map((r, i) => {
                          const isBest = i === 0 && r.name !== 'buyhold';
                          return (
                            <tr key={r.name} style={{
                              borderBottom: `1px solid ${COLORS.cardBorder}22`,
                              background: isBest ? COLORS.green + '11' : r.name === 'buyhold' ? COLORS.cyan + '08' : 'none',
                            }}>
                              <td style={{ padding: '3px 5px', color: isBest ? COLORS.green : r.name === 'buyhold' ? COLORS.cyan : COLORS.white, fontWeight: isBest ? 'bold' : 'normal', textTransform: 'capitalize' }}>
                                {r.name}{isBest ? ' ★' : ''}
                              </td>
                              {[1,2,3,4,5].map(q => (
                                <td key={q} style={{ padding: '3px 5px', textAlign: 'right', color: COLORS.textMuted, fontSize: 8 }}>
                                  {r.allocs?.[q] != null ? `${(r.allocs[q] * 100).toFixed(0)}%` : '--'}
                                </td>
                              ))}
                              <td style={{ padding: '3px 5px', textAlign: 'right', color: r.total_return > 0 ? COLORS.green : COLORS.red }}>
                                {r.total_return > 0 ? '+' : ''}{r.total_return?.toFixed(0)}%
                              </td>
                              <td style={{ padding: '3px 5px', textAlign: 'right', color: COLORS.white }}>
                                {r.annualized_return?.toFixed(1)}%
                              </td>
                              <td style={{ padding: '3px 5px', textAlign: 'right', color: isBest ? COLORS.green : COLORS.white, fontWeight: 'bold' }}>
                                {r.sharpe?.toFixed(3)}
                              </td>
                              <td style={{ padding: '3px 5px', textAlign: 'right', color: COLORS.red }}>
                                {r.max_drawdown?.toFixed(1)}%
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Winner bootstrap */}
                  {val.allocation_comparison.winner_bootstrap && (
                    <div style={{ fontSize: 9, color: COLORS.textMuted, marginTop: 6 }}>
                      Winner ({val.allocation_comparison.winner?.name}) bootstrap:
                      beats B&H in <span style={{ color: COLORS.green }}>{(val.allocation_comparison.winner_bootstrap.outperformance_rate * 100).toFixed(0)}%</span> of samples,
                      median outperformance <span style={{ color: COLORS.white }}>{val.allocation_comparison.winner_bootstrap.outperformance_median_pct > 0 ? '+' : ''}{val.allocation_comparison.winner_bootstrap.outperformance_median_pct?.toFixed(1)}%</span>
                    </div>
                  )}
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


function RegimeAnalysisPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    getRegimeAnalysis().then(r => { if (r && !r.error) setData(r); }).catch(() => {});
  }, []);

  const runAnalysis = async () => {
    setLoading(true);
    try {
      const r = await runRegimeAnalysis();
      if (r && !r.error) setData(r);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  return (
    <div style={{ marginTop: 12 }}>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '▾' : '▸'} Regime Analysis (Rates Up / Rates Down)
      </button>
      {expanded && (
        <div style={{ marginTop: 8, padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>REGIME-CONDITIONAL MODELS</span>
            <button onClick={runAnalysis} disabled={loading}
              style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              {loading ? 'RUNNING (~2-3 MIN)...' : data ? 'RE-RUN' : 'RUN REGIME ANALYSIS'}
            </button>
          </div>

          {!data && !loading && (
            <div style={{ color: COLORS.textDim, fontSize: 9 }}>
              Tests whether using different component weights during Rates Up vs Rates Down improves the signal.
              Monte Carlo validates if the regime split is statistically meaningful vs random splits.
              Takes ~2-3 minutes due to 5,000+ permutation tests.
            </div>
          )}

          {/* Current Regime */}
          {data?.current_regime && (
            <div style={{ padding: '6px 10px', marginBottom: 8, background: '#0a0a0a',
              borderLeft: `3px solid ${data.current_regime.regime_2 === 'rates_up' ? COLORS.red : COLORS.green}`,
              fontSize: 11 }}>
              <span style={{ color: COLORS.textMuted }}>Current regime: </span>
              <span style={{ color: data.current_regime.regime_2 === 'rates_up' ? COLORS.red : COLORS.green, fontWeight: 'bold' }}>
                {data.current_regime.regime_2 === 'rates_up' ? 'RATES UP' : 'RATES DOWN'}
              </span>
              <span style={{ color: COLORS.textDim, marginLeft: 8 }}>
                (10Y Δ6M: {data.current_regime.dgs10_chg_6m > 0 ? '+' : ''}{data.current_regime.dgs10_chg_6m?.toFixed(0)}bp)
              </span>
            </div>
          )}

          {/* Comparison Summary Table */}
          {data?.summary?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>REGIME MODEL COMPARISON</div>
              <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {['MODEL', 'SHARPE', 'MAX DD', 'REGIME MC p', 'Δ SHARPE'].map(h => (
                      <th key={h} style={{ textAlign: h === 'MODEL' ? 'left' : 'right', color: COLORS.textDim, padding: '3px 6px', fontSize: 8 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.summary.map((row, i) => {
                    const best = data.summary.reduce((a, b) => (a.sharpe || 0) > (b.sharpe || 0) ? a : b);
                    const isBest = row.sharpe === best.sharpe;
                    const delta = i === 0 ? null : ((row.sharpe || 0) - (data.summary[0].sharpe || 0));
                    return (
                      <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                        background: isBest ? COLORS.green + '11' : 'none' }}>
                        <td style={{ padding: '3px 6px', color: isBest ? COLORS.green : COLORS.white }}>
                          {isBest ? '★ ' : ''}{row.name}
                        </td>
                        <td style={{ padding: '3px 6px', textAlign: 'right', color: COLORS.amber, fontWeight: 'bold' }}>
                          {row.sharpe?.toFixed(3) ?? '--'}
                        </td>
                        <td style={{ padding: '3px 6px', textAlign: 'right', color: COLORS.red }}>
                          {row.max_dd != null ? `${row.max_dd.toFixed(1)}%` : '--'}
                        </td>
                        <td style={{ padding: '3px 6px', textAlign: 'right',
                          color: row.regime_p != null ? (row.regime_p < 0.05 ? COLORS.green : COLORS.red) : COLORS.textDim }}>
                          {row.regime_p != null ? row.regime_p.toFixed(4) : 'N/A'}
                        </td>
                        <td style={{ padding: '3px 6px', textAlign: 'right',
                          color: delta != null ? (delta > 0 ? COLORS.green : delta < 0 ? COLORS.red : COLORS.textDim) : COLORS.textDim }}>
                          {delta != null ? `${delta > 0 ? '+' : ''}${delta.toFixed(3)}` : '--'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* 2-Regime Detail */}
          {data?.regime_2 && !data.regime_2.error && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                2-REGIME WEIGHTS (Rates Up / Rates Down)
              </div>
              <div style={{ display: 'flex', gap: 16, fontSize: 10 }}>
                {Object.entries(data.regime_2.weights).map(([regime, info]) => (
                  <div key={regime} style={{ padding: '6px 10px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, flex: 1 }}>
                    <div style={{ color: regime === 'rates_up' ? COLORS.red : COLORS.green, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                      {regime === 'rates_up' ? 'RATES UP' : 'RATES DOWN'} (N={info.n_months})
                    </div>
                    {info.weights && Object.entries(info.weights).map(([k, v]) => (
                      <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9 }}>
                        <span style={{ color: COLORS.textDim }}>{W_LABELS[k] || k}</span>
                        <span style={{ color: COLORS.amber }}>{(v * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                    {info.oos_corr != null && (
                      <div style={{ marginTop: 3, fontSize: 8, color: (info.oos_corr || 0) < 0 ? COLORS.green : COLORS.red }}>
                        OOS corr: {info.oos_corr.toFixed(4)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              {/* Significance verdict */}
              <div style={{ marginTop: 4, fontSize: 9,
                color: data.regime_2.significant ? COLORS.green : COLORS.red,
                borderLeft: `3px solid ${data.regime_2.significant ? COLORS.green : COLORS.red}`,
                paddingLeft: 8, paddingTop: 2, paddingBottom: 2 }}>
                {data.regime_2.significant
                  ? `Regime split SIGNIFICANT (p=${data.regime_2.monte_carlo?.p_value?.toFixed(4)}) — 2-regime model is justified`
                  : `Regime split NOT significant (p=${data.regime_2.monte_carlo?.p_value?.toFixed(4)}) — stick with single-regime`}
              </div>
            </div>
          )}

          {/* 2-Regime MC Histogram */}
          {data?.regime_2?.monte_carlo?.histogram && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>
                2-REGIME MONTE CARLO — null Sharpe distribution ({data.regime_2.monte_carlo.n_permutations} shuffles)
              </div>
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={data.regime_2.monte_carlo.histogram.counts.map((c, i) => ({
                  bin: ((data.regime_2.monte_carlo.histogram.edges[i] + data.regime_2.monte_carlo.histogram.edges[i + 1]) / 2).toFixed(2),
                  count: c,
                }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                  <XAxis dataKey="bin" tick={{ fill: COLORS.textDim, fontSize: 7, fontFamily: FONT }} interval={4} />
                  <YAxis tick={{ fill: COLORS.textDim, fontSize: 7, fontFamily: FONT }} />
                  <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 9 }} />
                  <Bar dataKey="count" fill={COLORS.textDim} />
                  <ReferenceLine x={data.regime_2.monte_carlo.real_sharpe?.toFixed(2)} stroke={COLORS.cyan} strokeWidth={2} label={{ value: 'Real', fill: COLORS.cyan, fontSize: 8 }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* 3-Regime Detail */}
          {data?.regime_3 && !data.regime_3.error && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                3-REGIME WEIGHTS (Terciles: Falling Fast / Stable / Rising Fast)
              </div>
              <div style={{ display: 'flex', gap: 12, fontSize: 10 }}>
                {Object.entries(data.regime_3.weights).map(([regime, info]) => (
                  <div key={regime} style={{ padding: '6px 10px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, flex: 1 }}>
                    <div style={{ color: regime === 'rising_fast' ? COLORS.red : regime === 'falling_fast' ? COLORS.green : COLORS.amber,
                      fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                      {regime.replace('_', ' ').toUpperCase()} (N={info.n_months})
                    </div>
                    {info.weights && Object.entries(info.weights).map(([k, v]) => (
                      <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9 }}>
                        <span style={{ color: COLORS.textDim }}>{W_LABELS[k] || k}</span>
                        <span style={{ color: COLORS.amber }}>{(v * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 4, fontSize: 9,
                color: data.regime_3.significant ? COLORS.green : COLORS.red,
                borderLeft: `3px solid ${data.regime_3.significant ? COLORS.green : COLORS.red}`,
                paddingLeft: 8, paddingTop: 2, paddingBottom: 2 }}>
                {data.regime_3.significant
                  ? `Tercile split SIGNIFICANT (p=${data.regime_3.monte_carlo?.p_value?.toFixed(4)}) — 3-regime model is justified`
                  : `Tercile split NOT significant (p=${data.regime_3.monte_carlo?.p_value?.toFixed(4)}) — stick with simpler model`}
              </div>
            </div>
          )}

          {/* Regime Equity Curves */}
          {data?.regime_2?.equity_curve?.chart?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>
                EQUITY CURVES — 2-Regime vs Buy & Hold
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <ComposedChart data={data.regime_2.equity_curve.chart} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                  <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 8, fontFamily: FONT }}
                    tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: COLORS.textMuted, fontSize: 8, fontFamily: FONT }}
                    tickFormatter={v => v?.toFixed(1)} />
                  <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 9 }}
                    formatter={(v, name) => [v?.toFixed(3), name]} />
                  <Line type="monotone" dataKey="portfolio" stroke={COLORS.amber} strokeWidth={2} dot={false} name="2-Regime" connectNulls />
                  <Line type="monotone" dataKey="buyhold" stroke={COLORS.textDim} strokeWidth={1} dot={false} name="Buy & Hold" connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
              <div style={{ display: 'flex', gap: 12, justifyContent: 'center', fontSize: 8, color: COLORS.textDim }}>
                <span><span style={{ color: COLORS.amber }}>━</span> 2-Regime Strategy</span>
                <span><span style={{ color: COLORS.textDim }}>━</span> Buy & Hold</span>
              </div>
            </div>
          )}

          {/* Dynamic Weight Model */}
          {data?.dynamic && !data.dynamic.error && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: COLORS.amber, fontSize: 10, letterSpacing: 1, marginBottom: 6 }}>
                DYNAMIC WEIGHT MODEL (rate momentum + VIX conditioning)
              </div>

              {/* Current conditioning + weights */}
              {data.dynamic.current_conditioning && (
                <div style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
                  <div style={{ padding: '6px 10px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, flex: 1 }}>
                    <div style={{ color: COLORS.textDim, fontSize: 8, letterSpacing: 1, marginBottom: 3 }}>CURRENT CONDITIONING</div>
                    <div style={{ fontSize: 10 }}>
                      <span style={{ color: COLORS.textMuted }}>Rate momentum (z): </span>
                      <span style={{ color: (data.dynamic.current_conditioning.rate_z || 0) > 0 ? COLORS.red : COLORS.green, fontWeight: 'bold' }}>
                        {data.dynamic.current_conditioning.rate_z > 0 ? '+' : ''}{data.dynamic.current_conditioning.rate_z}
                      </span>
                      <span style={{ color: COLORS.textDim, marginLeft: 4, fontSize: 8 }}>
                        ({(data.dynamic.current_conditioning.rate_z || 0) > 0.5 ? 'rates rising fast' : (data.dynamic.current_conditioning.rate_z || 0) < -0.5 ? 'rates falling fast' : 'moderate'})
                      </span>
                    </div>
                    <div style={{ fontSize: 10 }}>
                      <span style={{ color: COLORS.textMuted }}>Vol regime (z): </span>
                      <span style={{ color: (data.dynamic.current_conditioning.vix_z || 0) > 0 ? COLORS.red : COLORS.green, fontWeight: 'bold' }}>
                        {data.dynamic.current_conditioning.vix_z > 0 ? '+' : ''}{data.dynamic.current_conditioning.vix_z}
                      </span>
                      <span style={{ color: COLORS.textDim, marginLeft: 4, fontSize: 8 }}>
                        ({(data.dynamic.current_conditioning.vix_z || 0) > 0.5 ? 'elevated vol' : (data.dynamic.current_conditioning.vix_z || 0) < -0.5 ? 'calm' : 'normal'})
                      </span>
                    </div>
                  </div>
                  <div style={{ padding: '6px 10px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, flex: 1 }}>
                    <div style={{ color: COLORS.textDim, fontSize: 8, letterSpacing: 1, marginBottom: 3 }}>CURRENT DYNAMIC WEIGHTS</div>
                    {data.dynamic.current_weights && Object.entries(data.dynamic.current_weights).map(([k, v]) => (
                      <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
                        <span style={{ color: COLORS.textMuted }}>{W_LABELS[k] || k}</span>
                        <span style={{ color: COLORS.amber, fontWeight: 'bold' }}>{(v * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                    <div style={{ marginTop: 3, fontSize: 8, color: COLORS.textDim }}>
                      vs Static: Qty 26% Credit 30% M2 44%
                    </div>
                  </div>
                </div>
              )}

              {/* Sensitivity table */}
              {data.dynamic.params?.sensitivities && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>WEIGHT SENSITIVITIES</div>
                  <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        {['COMPONENT', 'BASE', 'RATE SENS', 'VIX SENS'].map(h => (
                          <th key={h} style={{ textAlign: h === 'COMPONENT' ? 'left' : 'right', color: COLORS.textDim, padding: '3px 6px', fontSize: 8 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {['credit', 'm2'].map(comp => {
                        const s = data.dynamic.params.sensitivities[comp];
                        return s ? (
                          <tr key={comp} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                            <td style={{ padding: '3px 6px', color: COLORS.white }}>{comp === 'credit' ? 'Credit' : 'M2'}</td>
                            <td style={{ padding: '3px 6px', textAlign: 'right', color: COLORS.amber }}>{(s.base * 100).toFixed(0)}%</td>
                            <td style={{ padding: '3px 6px', textAlign: 'right',
                              color: Math.abs(s.rate_sens) > 0.02 ? (s.rate_sens > 0 ? COLORS.red : COLORS.green) : COLORS.textDim }}>
                              {s.rate_sens > 0 ? '+' : ''}{(s.rate_sens * 100).toFixed(1)}%/z
                            </td>
                            <td style={{ padding: '3px 6px', textAlign: 'right',
                              color: Math.abs(s.vix_sens) > 0.02 ? (s.vix_sens > 0 ? COLORS.red : COLORS.green) : COLORS.textDim }}>
                              {s.vix_sens > 0 ? '+' : ''}{(s.vix_sens * 100).toFixed(1)}%/z
                            </td>
                          </tr>
                        ) : null;
                      })}
                      <tr>
                        <td style={{ padding: '3px 6px', color: COLORS.white }}>Qty</td>
                        <td colSpan={3} style={{ padding: '3px 6px', textAlign: 'right', color: COLORS.textDim, fontSize: 8 }}>residual (1 - Credit - M2)</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}

              {/* Walk-forward results */}
              {data.dynamic.walkforward?.windows?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>
                    WALK-FORWARD (96M train / 24M test)
                    {data.dynamic.walkforward.summary?.sign_consistent != null && (
                      <span style={{ color: data.dynamic.walkforward.summary.sign_consistent ? COLORS.green : COLORS.red, marginLeft: 8 }}>
                        {data.dynamic.walkforward.summary.sign_consistent ? '✓ Sensitivities sign-consistent' : '⚠ Sensitivities flip sign across windows'}
                      </span>
                    )}
                  </div>
                  <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 4px' }}>Window</th>
                        <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>OOS Corr</th>
                        <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>Cr Rate</th>
                        <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>Cr VIX</th>
                        <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>M2 Rate</th>
                        <th style={{ textAlign: 'right', color: COLORS.textDim, padding: '2px 4px' }}>M2 VIX</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.dynamic.walkforward.windows.map((w, i) => (
                        <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                          <td style={{ padding: '2px 4px', color: COLORS.white }}>{w.period}</td>
                          <td style={{ padding: '2px 4px', textAlign: 'right',
                            color: (w.oos_corr || 0) < 0 ? COLORS.green : COLORS.red }}>
                            {w.oos_corr?.toFixed(3) ?? '--'}
                          </td>
                          {[1, 2, 4, 5].map(pi => (
                            <td key={pi} style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>
                              {w.params?.[pi] != null ? (w.params[pi] * 100).toFixed(1) + '%' : '--'}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {data.dynamic.walkforward.summary && (
                    <div style={{ fontSize: 8, color: COLORS.textMuted, marginTop: 2 }}>
                      Mean OOS: {data.dynamic.walkforward.summary.mean_oos?.toFixed(3) ?? '--'}
                      {data.dynamic.walkforward.summary.n_wrong_sign > 0 &&
                        <span style={{ color: COLORS.red }}> | {data.dynamic.walkforward.summary.n_wrong_sign}/{data.dynamic.walkforward.summary.n_windows} wrong-sign</span>}
                    </div>
                  )}
                </div>
              )}

              {/* Weight Evolution Chart */}
              {data.dynamic.equity_curve?.weight_history?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>
                    WEIGHT EVOLUTION (how component weights shift over time)
                  </div>
                  <ResponsiveContainer width="100%" height={180}>
                    <ComposedChart data={data.dynamic.equity_curve.weight_history.slice(-240)} margin={{ top: 5, right: 30, bottom: 5, left: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                      <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 7, fontFamily: FONT }}
                        tickFormatter={d => d?.slice(0, 4)} interval="preserveStartEnd" />
                      <YAxis yAxisId="w" domain={[0, 100]} tick={{ fill: COLORS.textMuted, fontSize: 7, fontFamily: FONT }}
                        tickFormatter={v => `${v}%`} />
                      <YAxis yAxisId="z" orientation="right" domain={[-2, 2]} tick={{ fill: COLORS.textDim, fontSize: 7, fontFamily: FONT }} />
                      <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 9 }}
                        formatter={(v, name) => [name === 'rate_z' ? v?.toFixed(2) : `${v?.toFixed(0)}%`, name]} />
                      <Area yAxisId="w" type="monotone" dataKey="m2" stackId="1" fill={COLORS.green} fillOpacity={0.3} stroke={COLORS.green} strokeWidth={0} name="M2" />
                      <Area yAxisId="w" type="monotone" dataKey="credit" stackId="1" fill={COLORS.cyan} fillOpacity={0.3} stroke={COLORS.cyan} strokeWidth={0} name="Credit" />
                      <Area yAxisId="w" type="monotone" dataKey="qty" stackId="1" fill={COLORS.textDim} fillOpacity={0.3} stroke={COLORS.textDim} strokeWidth={0} name="Qty" />
                      <Line yAxisId="z" type="monotone" dataKey="rate_z" stroke={COLORS.red} strokeWidth={1} dot={false} name="Rate z" strokeOpacity={0.6} />
                    </ComposedChart>
                  </ResponsiveContainer>
                  <div style={{ display: 'flex', gap: 12, justifyContent: 'center', fontSize: 7, color: COLORS.textDim }}>
                    <span><span style={{ color: COLORS.textDim }}>■</span> Qty</span>
                    <span><span style={{ color: COLORS.cyan }}>■</span> Credit</span>
                    <span><span style={{ color: COLORS.green }}>■</span> M2</span>
                    <span><span style={{ color: COLORS.red }}>─</span> Rate z</span>
                  </div>
                </div>
              )}

              {/* Dynamic MC Histogram */}
              {data.dynamic.monte_carlo?.histogram && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 3 }}>
                    DYNAMIC MC — null Sharpe distribution ({data.dynamic.monte_carlo.n_permutations} shuffles of conditioning variables)
                  </div>
                  <ResponsiveContainer width="100%" height={120}>
                    <BarChart data={data.dynamic.monte_carlo.histogram.counts.map((c, i) => ({
                      bin: ((data.dynamic.monte_carlo.histogram.edges[i] + data.dynamic.monte_carlo.histogram.edges[i + 1]) / 2).toFixed(2),
                      count: c,
                    }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                      <XAxis dataKey="bin" tick={{ fill: COLORS.textDim, fontSize: 7, fontFamily: FONT }} interval={4} />
                      <YAxis tick={{ fill: COLORS.textDim, fontSize: 7, fontFamily: FONT }} />
                      <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 9 }} />
                      <Bar dataKey="count" fill={COLORS.textDim} />
                      <ReferenceLine x={data.dynamic.monte_carlo.real_sharpe?.toFixed(2)} stroke={COLORS.amber} strokeWidth={2}
                        label={{ value: 'Real', fill: COLORS.amber, fontSize: 8 }} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Significance verdict */}
              <div style={{ fontSize: 9,
                color: data.dynamic.significant ? COLORS.green : COLORS.red,
                borderLeft: `3px solid ${data.dynamic.significant ? COLORS.green : COLORS.red}`,
                paddingLeft: 8, paddingTop: 2, paddingBottom: 2, marginBottom: 4 }}>
                {data.dynamic.significant
                  ? `Dynamic conditioning SIGNIFICANT (p=${data.dynamic.monte_carlo?.p_value?.toFixed(4)}) — rate/VIX improve weight selection`
                  : `Dynamic conditioning NOT significant (p=${data.dynamic.monte_carlo?.p_value?.toFixed(4)}) — static weights sufficient`}
              </div>
            </div>
          )}

          {/* Decision recommendation */}
          {data?.regime_2 && (
            <div style={{ padding: '6px 10px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`,
              fontSize: 9, color: COLORS.textSecondary, lineHeight: 1.6 }}>
              <strong style={{ color: COLORS.amber }}>RECOMMENDATION: </strong>
              {(() => {
                const dynWins = data.dynamic?.significant && data.dynamic?.sharpe > (data.baseline?.sharpe || 0) && data.dynamic?.walkforward?.summary?.sign_consistent;
                const r2Wins = data.regime_2?.significant && data.regime_2?.sharpe > (data.baseline?.sharpe || 0);
                const r3Wins = data.regime_3?.significant && data.regime_3?.sharpe > (data.baseline?.sharpe || 0);
                if (dynWins) return 'Use dynamic weight model — conditioning variables are significant, walk-forward stable, and Sharpe improves over static.';
                if (r2Wins && r3Wins && data.regime_3.sharpe > data.regime_2.sharpe) return 'Use 3-regime model — both splits significant and terciles add value.';
                if (r2Wins) return 'Use 2-regime model — regime split is significant and improves Sharpe.';
                return 'Stick with single-regime 3FA — no regime or dynamic model shows statistically significant improvement.';
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function ImprovementsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [runTrack, setRunTrack] = useState('all');

  useEffect(() => {
    getImprovements().then(r => { if (r && !r.error) setData(r); }).catch(() => {});
  }, []);

  const run = async (track) => {
    setLoading(true); setRunTrack(track);
    try {
      const r = await runImprovements(track);
      if (r && !r.error) setData(r);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const S = { hdr: { color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 },
    card: { padding: '8px 12px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, marginBottom: 8 } };

  return (
    <div style={{ marginTop: 12 }}>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '▾' : '▸'} Model Improvement Study (5 Tracks)
      </button>
      {expanded && (
        <div style={{ marginTop: 8, padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
            <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>MODEL IMPROVEMENTS</span>
            {['all', 'tail', 'proxy', 'timing', 'position', 'combination', 'allocation', 'horizon', 'crash', 'crisis', 'conviction', 'probability', 'xsect', 'realtime'].map(t => (
              <button key={t} onClick={() => run(t)} disabled={loading}
                style={{ padding: '2px 8px', background: 'none', color: COLORS.cyan,
                  border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
                {loading && runTrack === t ? '...' : t.toUpperCase()}
              </button>
            ))}
          </div>

          {!data && !loading && (
            <div style={{ color: COLORS.textDim, fontSize: 9 }}>
              5 research tracks: Tail Events, Factor Proxies, Signal Timing, Portfolio Construction, Combination Methods.
              Click ALL to run everything, or individual track buttons.
            </div>
          )}

          {/* Track 5: Tail Events */}
          {data?.tail && !data.tail.error && (
            <div style={S.card}>
              <div style={S.hdr}>TRACK 5 — TAIL EVENT CASE STUDIES</div>
              <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['EVENT', 'SPY DD', 'STRAT DD', 'Q ENTER', 'MONTHS LATE', 'FAILURE MODE'].map(h => (
                    <th key={h} style={{ textAlign: h === 'EVENT' || h === 'FAILURE MODE' ? 'left' : 'right',
                      color: COLORS.textDim, padding: '2px 4px', fontSize: 8 }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {data.tail.case_studies?.map(cs => (
                    <tr key={cs.name} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                      <td style={{ padding: '2px 4px', color: COLORS.white }}>{cs.name}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{cs.spy_drawdown}%</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{cs.strategy_drawdown != null ? `${cs.strategy_drawdown}%` : '--'}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: (cs.quintile_at_start || 0) >= 4 ? COLORS.green : COLORS.textMuted }}>Q{cs.quintile_at_start || '?'}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{cs.months_to_defensive ?? 'never'}</td>
                      <td style={{ padding: '2px 4px', color: cs.failure_mode?.includes('CORRECT') ? COLORS.green : cs.failure_mode?.includes('WRONG') ? COLORS.red : COLORS.amber, fontSize: 8 }}>
                        {cs.failure_mode}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ fontSize: 8, color: COLORS.textDim, marginTop: 4 }}>{data.tail.summary?.verdict}</div>
            </div>
          )}

          {/* Track 4: Factor Proxies */}
          {data?.proxy && !data.proxy.error && (
            <div style={S.card}>
              <div style={S.hdr}>TRACK 4 — FACTOR PROXY QUALITY</div>
              <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['PROXY', 'FACTOR', 'CORR 6M', 'OOS CORR', 'N'].map(h => (
                    <th key={h} style={{ textAlign: h === 'PROXY' || h === 'FACTOR' ? 'left' : 'right',
                      color: COLORS.textDim, padding: '2px 4px', fontSize: 8 }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {data.proxy.proxy_results?.map(pr => (
                    <tr key={pr.name} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                      background: pr.is_baseline ? COLORS.amber + '08' : 'none' }}>
                      <td style={{ padding: '2px 4px', color: pr.is_baseline ? COLORS.amber : COLORS.white, fontSize: 8 }}>{pr.name}{pr.is_baseline ? ' ★' : ''}</td>
                      <td style={{ padding: '2px 4px', color: COLORS.textDim, fontSize: 8 }}>{W_LABELS[pr.factor] || pr.factor}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: (pr.corr_6m || 0) < 0 ? COLORS.green : COLORS.red }}>{pr.corr_6m?.toFixed(3) ?? '--'}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: (pr.oos_corr_6m || 0) < 0 ? COLORS.green : COLORS.red }}>{pr.oos_corr_6m?.toFixed(3) ?? '--'}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textDim }}>{pr.n_months}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.proxy.improvement != null && (
                <div style={{ fontSize: 9, marginTop: 4, color: data.proxy.improvement > 0 ? COLORS.green : COLORS.textDim }}>
                  Best-combo: {data.proxy.best_combo_sharpe} vs Baseline: {data.proxy.baseline_sharpe} (Δ{data.proxy.improvement > 0 ? '+' : ''}{data.proxy.improvement})
                </div>
              )}
            </div>
          )}

          {/* Track 1: Timing */}
          {data?.timing && !data.timing.error && (
            <div style={S.card}>
              <div style={S.hdr}>TRACK 1 — SIGNAL TIMING & LEAD/LAG</div>
              {data.timing.cross_correlations && Object.entries(data.timing.cross_correlations).map(([k, v]) => (
                <div key={k} style={{ fontSize: 9, display: 'flex', gap: 8 }}>
                  <span style={{ color: COLORS.textMuted, width: 55 }}>{W_LABELS[k] || k}</span>
                  <span style={{ color: COLORS.amber }}>Lag {v.best_lag_6m}M</span>
                  <span style={{ color: COLORS.textDim }}>corr={v.best_corr_6m?.toFixed(3)} (contemp={v.contemporaneous_corr_6m?.toFixed(3)})</span>
                </div>
              ))}
              {data.timing.staggered_model && (
                <div style={{ fontSize: 9, marginTop: 4, color: data.timing.staggered_model.improvement > 0 ? COLORS.green : COLORS.textDim }}>
                  Staggered: {data.timing.staggered_model.staggered?.sharpe} vs Contemp: {data.timing.staggered_model.contemporaneous?.sharpe} (Δ{data.timing.staggered_model.improvement > 0 ? '+' : ''}{data.timing.staggered_model.improvement})
                </div>
              )}
              {data.timing.best_transform_model && !data.timing.best_transform_model.error && (
                <div style={{ fontSize: 9, marginTop: 2 }}>
                  <span style={{ color: COLORS.textDim }}>Best transforms: </span>
                  {Object.entries(data.timing.best_transform_model.best_transforms || {}).map(([k, t]) => (
                    <span key={k} style={{ marginRight: 6 }}><span style={{ color: COLORS.textMuted }}>{W_LABELS[k] || k}=</span><span style={{ color: COLORS.amber }}>{t}</span></span>
                  ))}
                  <span style={{ color: data.timing.best_transform_model.improvement > 0 ? COLORS.green : COLORS.textDim }}>
                    (Δ{data.timing.best_transform_model.improvement > 0 ? '+' : ''}{data.timing.best_transform_model.improvement})
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Track 3: Position Sizing */}
          {data?.position && !data.position.error && (
            <div style={S.card}>
              <div style={S.hdr}>TRACK 3 — PORTFOLIO CONSTRUCTION</div>
              <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['METHOD', 'SHARPE', 'MAX DD', 'CALMAR', 'TURN', 'NET'].map(h => (
                    <th key={h} style={{ textAlign: h === 'METHOD' ? 'left' : 'right',
                      color: COLORS.textDim, padding: '2px 3px', fontSize: 7 }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {data.position.variants?.slice(0, 10).map((v, i) => (
                    <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11`,
                      background: v.is_best ? COLORS.green + '11' : 'none' }}>
                      <td style={{ padding: '2px 3px', color: v.is_best ? COLORS.green : COLORS.white, fontSize: 8 }}>{v.is_best ? '★ ' : ''}{v.name}</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.amber }}>{v.sharpe}</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.red }}>{v.max_dd}%</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>{v.calmar}</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textDim }}>{v.turnover?.toFixed(3)}</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>{v.net_sharpe}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Track 2: Combination Methods */}
          {data?.combination && !data.combination.error && (
            <div style={S.card}>
              <div style={S.hdr}>TRACK 2 — SIGNAL COMBINATION METHODS</div>
              <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['METHOD', 'SHARPE', 'MAX DD', 'OOS CORR', 'Δ', 'PARAMS'].map(h => (
                    <th key={h} style={{ textAlign: h === 'METHOD' ? 'left' : 'right',
                      color: COLORS.textDim, padding: '2px 4px', fontSize: 8 }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {data.combination.methods?.map((m, i) => (
                    <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                      background: m.is_best ? COLORS.green + '11' : 'none' }}>
                      <td style={{ padding: '2px 4px', color: m.is_best ? COLORS.green : COLORS.white, fontSize: 8 }}>{m.is_best ? '★ ' : ''}{m.name}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.amber }}>{m.sharpe}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{m.max_dd}%</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: (m.oos_corr_6m || 0) < 0 ? COLORS.green : COLORS.red }}>{m.oos_corr_6m?.toFixed(3) ?? '--'}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right',
                        color: (m.delta_sharpe || 0) > 0 ? COLORS.green : (m.delta_sharpe || 0) < 0 ? COLORS.red : COLORS.textDim }}>
                        {m.delta_sharpe != null ? `${m.delta_sharpe > 0 ? '+' : ''}${m.delta_sharpe}` : '--'}</td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textDim }}>{m.n_params}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.combination.robustness_note && (
                <div style={{ fontSize: 8, color: COLORS.amber, marginTop: 4 }}>{data.combination.robustness_note}</div>
              )}
            </div>
          )}

          {/* Allocation Optimization */}
          {data?.allocation && !data.allocation.error && (
            <div style={S.card}>
              <div style={S.hdr}>ALLOCATION OPTIMIZATION — Grid Search + Continuous Functions</div>

              {/* Summary comparison */}
              {data.allocation.summary?.length > 0 && (
                <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%', marginBottom: 8 }}>
                  <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {['APPROACH', 'SHARPE', 'MAX DD', 'CALMAR', 'TOTAL RET', 'TURN'].map(h => (
                      <th key={h} style={{ textAlign: h === 'APPROACH' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 4px', fontSize: 8 }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {data.allocation.summary.map((r, i) => (
                      <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`, background: i === 1 ? COLORS.green + '11' : 'none' }}>
                        <td style={{ padding: '2px 4px', color: i === 1 ? COLORS.green : COLORS.white, fontSize: 8 }}>{i === 1 ? '★ ' : ''}{r.name}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.amber }}>{r.sharpe}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{r.max_dd}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{r.calmar}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.white }}>{r.total_return}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textDim }}>{r.turnover?.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {/* Grid search top 5 by Sharpe */}
              {data.allocation.grid_search?.top_by_sharpe?.length > 0 && (
                <div style={{ marginBottom: 6 }}>
                  <div style={{ fontSize: 8, color: COLORS.textDim, marginBottom: 2 }}>Top 5 by Sharpe (grid search, vol-scaled):</div>
                  {data.allocation.grid_search.top_by_sharpe.slice(0, 5).map((r, i) => (
                    <div key={i} style={{ fontSize: 8, display: 'flex', gap: 8 }}>
                      <span style={{ color: i === 0 ? COLORS.green : COLORS.white, width: 120 }}>{r.label}</span>
                      <span style={{ color: COLORS.amber }}>Sharpe={r.sharpe}</span>
                      <span style={{ color: COLORS.red }}>DD={r.max_dd}%</span>
                      <span style={{ color: COLORS.textDim }}>Calmar={r.calmar}</span>
                      <span style={{ color: COLORS.textMuted }}>Ret={r.total_return}%</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Monte Carlo */}
              {data.allocation.grid_search?.monte_carlo && (
                <div style={{ fontSize: 9, color: data.allocation.grid_search.monte_carlo.p_value < 0.05 ? COLORS.green : COLORS.red,
                  borderLeft: `3px solid ${data.allocation.grid_search.monte_carlo.p_value < 0.05 ? COLORS.green : COLORS.red}`,
                  paddingLeft: 8, marginBottom: 6 }}>
                  Grid best MC: p={data.allocation.grid_search.monte_carlo.p_value} (real Sharpe={data.allocation.grid_search.monte_carlo.real_sharpe} vs null mean={data.allocation.grid_search.monte_carlo.null_mean})
                </div>
              )}

              {/* Continuous functions */}
              {data.allocation.continuous?.functions?.length > 0 && (
                <div>
                  <div style={{ fontSize: 8, color: COLORS.textDim, marginBottom: 2 }}>Continuous mapping functions:</div>
                  {data.allocation.continuous.functions.map((f, i) => (
                    <div key={i} style={{ fontSize: 8, display: 'flex', gap: 8 }}>
                      <span style={{ color: f.is_best ? COLORS.green : COLORS.white, width: 180 }}>{f.is_best ? '★ ' : ''}{f.name}</span>
                      <span style={{ color: COLORS.amber }}>Sharpe={f.sharpe}</span>
                      <span style={{ color: COLORS.red }}>DD={f.max_dd}%</span>
                      <span style={{ color: COLORS.textMuted }}>Ret={f.total_return}%</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Forward Horizon Analysis — Multi-Model */}
          {data?.horizon && !data.horizon.error && (
            <div style={S.card}>
              <div style={S.hdr}>
                FORWARD HORIZON ANALYSIS — Macro (3FA) vs Market (2F) vs Combined (5F)
                {data.horizon.has_cash_yield && (
                  <span style={{ color: COLORS.amber, marginLeft: 8 }}>FF: {data.horizon.current_ff_rate}% (avg {data.horizon.avg_ff_rate}%)</span>
                )}
              </div>

              {/* Cross-model comparison at 6M */}
              {data.horizon.cross_comparison_6m?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 8, color: COLORS.textDim, marginBottom: 2 }}>CROSS-MODEL COMPARISON (6M horizon, with cash yield)</div>
                  <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                    <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                      {['MODEL', 'SHARPE', 'SORTINO', 'MAX DD', 'CALMAR', 'TOTAL RET', 'GAP vs B&H', 'DEF%'].map(h => (
                        <th key={h} style={{ textAlign: h === 'MODEL' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 4px', fontSize: 7 }}>{h}</th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {data.horizon.cross_comparison_6m.map((r, i) => (
                        <tr key={r.model} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                          background: i === 0 ? COLORS.green + '11' : 'none' }}>
                          <td style={{ padding: '2px 4px', color: i === 0 ? COLORS.green : COLORS.white, fontWeight: i === 0 ? 'bold' : 'normal', fontSize: 8 }}>
                            {i === 0 ? '★ ' : ''}{r.model_label}
                          </td>
                          <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.amber, fontWeight: 'bold' }}>{r.sharpe}</td>
                          <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{r.sortino}</td>
                          <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{r.max_dd}%</td>
                          <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{r.calmar}</td>
                          <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.white }}>{r.total_return}%</td>
                          <td style={{ padding: '2px 4px', textAlign: 'right', color: (r.gap_vs_bh || 0) > 0 ? COLORS.green : COLORS.red }}>{r.gap_vs_bh}%</td>
                          <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textDim }}>{r.pct_defensive}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Per-model horizon tables */}
              {data.horizon.models && Object.entries(data.horizon.models).map(([mk, mr]) => {
                if (mr.error || !mr.summary?.length) return null;
                const mColors = { '5f': COLORS.green, '3fa_eq': COLORS.amber, '2f': COLORS.cyan };
                return (
                  <div key={mk} style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 8, color: mColors[mk] || COLORS.white, marginBottom: 2 }}>
                      {mr.model_label} — Alloc: {mr.alloc_rule && Object.values(mr.alloc_rule).map(v => `${Math.round(v*100)}%`).join('/')}
                    </div>
                    <div style={{ overflowX: 'auto' }}>
                      <table style={{ fontSize: 7, borderCollapse: 'collapse', minWidth: '100%' }}>
                        <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                          {['HOR', 'CORR', 'SHARPE', 'SORTINO', 'S+CASH', 'DD', 'RET+CASH', 'B&H', 'GAP', 'DEF%', 'TURN/Y'].map(h => (
                            <th key={h} style={{ textAlign: h === 'HOR' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 3px', fontSize: 6, whiteSpace: 'nowrap' }}>{h}</th>
                          ))}
                        </tr></thead>
                        <tbody>
                          {mr.summary.map(r => (
                            <tr key={r.horizon} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11`,
                              background: r.is_best ? (mColors[mk] || COLORS.green) + '11' : 'none' }}>
                              <td style={{ padding: '2px 3px', color: r.is_best ? mColors[mk] || COLORS.green : COLORS.white, fontWeight: r.is_best ? 'bold' : 'normal' }}>
                                {r.is_best ? '★ ' : ''}{r.horizon}
                              </td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: (r.signal_corr || 0) < 0 ? COLORS.green : COLORS.red }}>{r.signal_corr?.toFixed(3) ?? '--'}</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>{r.sharpe_no_cash}</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>{r.sortino_no_cash}</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.amber, fontWeight: 'bold' }}>{r.sharpe_with_cash}</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.red }}>{r.max_dd}%</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.white }}>{r.total_return_with_cash}%</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textDim }}>{r.bh_total_return}%</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: (r.gap_vs_bh || 0) > 0 ? COLORS.green : COLORS.red }}>{r.gap_vs_bh}%</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textDim }}>{r.pct_defensive}%</td>
                              <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textDim }}>{r.q_changes_per_yr}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                );
              })}
              <div style={{ fontSize: 7, color: COLORS.textDim, marginTop: 4 }}>
                ★ = best Sharpe+Cash per model. SPY total return (dividends). Historical monthly Fed Funds on cash.
                5F = Qty+M2+Credit+Dollar+Rates (combined). 3FA = Qty+Credit+M2 (macro). 2F = HY OAS+Xccy (market).
              </div>
            </div>
          )}

          {/* Crash Robustness */}
          {data?.crash && !data.crash.error && (
            <div style={S.card}>
              <div style={S.hdr}>CRASH ROBUSTNESS — Bootstrap + Perturbation + Additional Stress</div>

              {/* Robustness score */}
              <div style={{ padding: '6px 10px', marginBottom: 8, background: '#0a0a0a',
                borderLeft: `3px solid ${(data.crash.robustness_score_partial || 0) > 0.6 ? COLORS.green : COLORS.amber}`,
                fontSize: 12 }}>
                <span style={{ color: COLORS.textMuted }}>Robustness Score: </span>
                <span style={{ color: (data.crash.robustness_score_partial || 0) > 0.6 ? COLORS.green : COLORS.amber, fontWeight: 'bold', fontSize: 16 }}>
                  {((data.crash.robustness_score_partial || 0) * 100).toFixed(0)}%
                </span>
                <span style={{ color: COLORS.textDim, fontSize: 9, marginLeft: 8 }}>(excl crisis injection)</span>
              </div>

              {/* Bootstrap results */}
              {data.crash.bootstrap_6m && !data.crash.bootstrap_6m.error && (() => {
                const b = data.crash.bootstrap_6m;
                return (
                  <div style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 8, color: COLORS.textDim, marginBottom: 2 }}>BLOCK BOOTSTRAP (1000 synthetic histories, 6M blocks)</div>
                    <div style={{ fontSize: 9 }}>
                      <span style={{ color: COLORS.textMuted }}>Detection rate: </span>
                      <span style={{ color: COLORS.green, fontWeight: 'bold' }}>{(b.mean_detection_rate * 100).toFixed(0)}%</span>
                      <span style={{ color: COLORS.textDim, marginLeft: 6 }}>±{(b.std_detection_rate * 100).toFixed(0)}%</span>
                      <span style={{ color: COLORS.textDim, marginLeft: 6 }}>({b.pct_above_70}% of sims ≥70%)</span>
                    </div>
                    <div style={{ fontSize: 8, color: COLORS.textDim }}>
                      Avg Q at crash: {b.avg_quintile_at_crash} | Avg Q non-crash: {b.avg_quintile_non_crash} | FP rate: {(b.mean_false_positive_rate * 100).toFixed(0)}%
                    </div>
                    {data.crash.bootstrap_3m && !data.crash.bootstrap_3m.error && data.crash.bootstrap_12m && !data.crash.bootstrap_12m.error && (
                      <div style={{ fontSize: 8, color: COLORS.textDim }}>
                        Sensitivity: 3M blocks={((data.crash.bootstrap_3m.mean_detection_rate || 0) * 100).toFixed(0)}% | 12M blocks={((data.crash.bootstrap_12m.mean_detection_rate || 0) * 100).toFixed(0)}%
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* Perturbation results */}
              {data.crash.perturbation && (
                <div style={{ marginBottom: 6 }}>
                  <div style={{ fontSize: 8, color: COLORS.textDim, marginBottom: 2 }}>
                    PERTURBATION TEST — survival rate: <span style={{ color: COLORS.amber }}>{((data.crash.perturbation.survival_rate || 0) * 100).toFixed(0)}%</span> ({data.crash.perturbation.n_perturbations} tests)
                  </div>
                  <div style={{ maxHeight: 150, overflowY: 'auto' }}>
                    <table style={{ fontSize: 7, borderCollapse: 'collapse', width: '100%' }}>
                      <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        {['EVENT', 'BASE Q', 'TYPE', 'PARAM', 'Q', 'DETECTED'].map(h => (
                          <th key={h} style={{ textAlign: h === 'EVENT' || h === 'TYPE' || h === 'PARAM' ? 'left' : 'right', color: COLORS.textDim, padding: '1px 3px', fontSize: 7 }}>{h}</th>
                        ))}
                      </tr></thead>
                      <tbody>
                        {data.crash.perturbation.events?.flatMap(e => e.perturbations?.map((p, i) => (
                          <tr key={`${e.event}-${i}`} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                            <td style={{ padding: '1px 3px', color: COLORS.white, fontSize: 7 }}>{i === 0 ? e.event : ''}</td>
                            <td style={{ padding: '1px 3px', textAlign: 'right', color: COLORS.textDim }}>{i === 0 ? e.base_quintile : ''}</td>
                            <td style={{ padding: '1px 3px', color: COLORS.textMuted }}>{p.type}</td>
                            <td style={{ padding: '1px 3px', color: COLORS.textDim }}>{p.param}</td>
                            <td style={{ padding: '1px 3px', textAlign: 'right', color: p.quintile >= 4 ? COLORS.green : COLORS.red }}>{p.quintile}</td>
                            <td style={{ padding: '1px 3px', textAlign: 'right', color: p.detected ? COLORS.green : COLORS.red }}>{p.detected ? '✓' : '✗'}</td>
                          </tr>
                        )))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Additional stress events */}
              {data.crash.additional_stress && (
                <div>
                  <div style={{ fontSize: 8, color: COLORS.textDim, marginBottom: 2 }}>
                    ADDITIONAL STRESS — accuracy: <span style={{ color: COLORS.amber }}>{((data.crash.additional_stress.accuracy || 0) * 100).toFixed(0)}%</span> ({data.crash.additional_stress.n_correct}/{data.crash.additional_stress.n_events}), FP: {data.crash.additional_stress.false_positives}
                  </div>
                  <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                    <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                      {['EVENT', 'SPX DD', 'REAL?', 'Q BEFORE', 'Q START', 'Q TROUGH', 'DEFENSIVE', 'CORRECT'].map(h => (
                        <th key={h} style={{ textAlign: h === 'EVENT' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 3px', fontSize: 7 }}>{h}</th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {data.crash.additional_stress.events?.map(e => (
                        <tr key={e.name} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                          <td style={{ padding: '2px 3px', color: COLORS.white }}>{e.name}</td>
                          <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.red }}>{e.spx_dd}%</td>
                          <td style={{ padding: '2px 3px', textAlign: 'right', color: e.is_real_crash ? COLORS.red : COLORS.textDim }}>{e.is_real_crash ? 'YES' : 'no'}</td>
                          <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>Q{e.q_before}</td>
                          <td style={{ padding: '2px 3px', textAlign: 'right', color: e.q_at_start >= 4 ? COLORS.green : COLORS.textMuted }}>Q{e.q_at_start}</td>
                          <td style={{ padding: '2px 3px', textAlign: 'right', color: e.q_at_trough >= 4 ? COLORS.green : COLORS.textMuted }}>Q{e.q_at_trough}</td>
                          <td style={{ padding: '2px 3px', textAlign: 'right', color: e.was_defensive ? COLORS.green : COLORS.red }}>{e.was_defensive ? 'YES' : 'NO'}</td>
                          <td style={{ padding: '2px 3px', textAlign: 'right', color: e.correct_call ? COLORS.green : COLORS.red }}>{e.correct_call ? '✓' : '✗'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Crisis Injection */}
          {data?.crisis && !data.crisis.error && (
            <div style={S.card}>
              <div style={S.hdr}>
                CRISIS INJECTION — {data.crisis.n_detected}/{data.crisis.n_total} detected ({((data.crisis.detection_rate || 0) * 100).toFixed(0)}%)
              </div>
              {data.crisis.scenario_summary?.length > 0 && (
                <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%', marginBottom: 6 }}>
                  <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {['SCENARIO', 'DETECTED', 'RATE', 'AVG MONTHS'].map(h => (
                      <th key={h} style={{ textAlign: h === 'SCENARIO' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 4px', fontSize: 7 }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {data.crisis.scenario_summary.map(s => (
                      <tr key={s.scenario} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                        <td style={{ padding: '2px 4px', color: COLORS.white, fontSize: 8 }}>{s.label}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{s.detected}/{s.total}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: s.detection_rate >= 0.6 ? COLORS.green : COLORS.red }}>
                          {(s.detection_rate * 100).toFixed(0)}%
                        </td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textDim }}>{s.avg_months_to_detect ?? '--'}M</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Signal Conviction */}
          {data?.conviction && (
            <div style={S.card}>
              <div style={S.hdr}>SIGNAL CONVICTION — Momentum / Consensus / VIX Confirmation</div>
              {data.conviction.comparison?.length > 0 && (
                <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                  <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {['METHOD', 'CRASHES', 'SHARPE', 'SORTINO', 'DD', 'TOTAL RET', 'DEF%'].map(h => (
                      <th key={h} style={{ textAlign: h === 'METHOD' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 4px', fontSize: 7 }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {data.conviction.comparison.map((m, i) => (
                      <tr key={m.method} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                        background: i === 0 ? COLORS.amber + '08' : 'none' }}>
                        <td style={{ padding: '2px 4px', color: i === 0 ? COLORS.amber : COLORS.white, fontSize: 8 }}>{m.method}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: m.crashes?.startsWith('4') ? COLORS.green : COLORS.red }}>{m.crashes}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.amber }}>{m.sharpe}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{m.sortino}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{m.max_dd}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.white }}>{m.total_return}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: (m.pct_defensive || 0) < 30 ? COLORS.green : COLORS.textMuted }}>{m.pct_defensive}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Crash Probability */}
          {data?.probability?.error && (
            <div style={S.card}>
              <div style={S.hdr}>CRASH PROBABILITY — Error</div>
              <div style={{ color: COLORS.red, fontSize: 9 }}>{data.probability.error}</div>
            </div>
          )}
          {data?.probability && !data.probability.error && (
            <div style={S.card}>
              <div style={S.hdr}>CRASH PROBABILITY — Logistic Regression P(crash in 3M)</div>
              {data.probability.current_probability != null && (
                <div style={{ padding: '6px 10px', marginBottom: 6, background: '#0a0a0a',
                  borderLeft: `3px solid ${data.probability.current_probability > 0.2 ? COLORS.red : COLORS.green}`, fontSize: 12 }}>
                  <span style={{ color: COLORS.textMuted }}>Current P(crash): </span>
                  <span style={{ color: data.probability.current_probability > 0.2 ? COLORS.red : COLORS.green, fontWeight: 'bold', fontSize: 18 }}>
                    {(data.probability.current_probability * 100).toFixed(1)}%
                  </span>
                </div>
              )}
              <div style={{ fontSize: 9, marginBottom: 6 }}>
                <span style={{ color: COLORS.textMuted }}>OOS: </span>
                <span style={{ color: COLORS.amber }}>AUC={data.probability.roc_auc}</span>
                <span style={{ color: COLORS.textDim, marginLeft: 8 }}>Prec@20%={data.probability.precision_at_20pct} Rec@20%={data.probability.recall_at_20pct}</span>
                <span style={{ color: COLORS.textDim, marginLeft: 8 }}>Crashes={data.probability.crash_detection?.detected}/4</span>
              </div>
              <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%', marginBottom: 4 }}>
                <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['APPROACH', 'SHARPE', 'SORTINO', 'DD', 'RET', 'DEF%'].map(h => (
                    <th key={h} style={{ textAlign: h === 'APPROACH' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 3px', fontSize: 7 }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {[['Baseline (flat)', data.probability.baseline_metrics],
                    ['Logistic (discrete)', data.probability.discrete_metrics],
                    ['Logistic (continuous)', data.probability.continuous_metrics]].map(([label, m]) => m ? (
                    <tr key={label} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                      <td style={{ padding: '2px 3px', color: COLORS.white, fontSize: 8 }}>{label}</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.amber }}>{m.sharpe}</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>{m.sortino}</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.red }}>{m.max_dd}%</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.white }}>{m.total_return}%</td>
                      <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textDim }}>{m.pct_defensive}%</td>
                    </tr>
                  ) : null)}
                </tbody>
              </table>
              {data.probability.feature_importance?.length > 0 && (
                <div style={{ fontSize: 7, color: COLORS.textDim }}>
                  Top features: {data.probability.feature_importance.slice(0, 5).map(f => `${f.feature}(${f.coefficient > 0 ? '+' : ''}${f.coefficient})`).join(', ')}
                </div>
              )}
            </div>
          )}

          {/* Cross-Sectional Strategy */}
          {data?.xsect && !data.xsect.error && (
            <div style={S.card}>
              <div style={S.hdr}>
                CROSS-SECTIONAL STRATEGY — {data.xsect.n_assets} assets, {data.xsect.n_pro} pro / {data.xsect.n_anti} anti liquidity
                <span style={{ color: data.xsect.current_regime === 'bullish' ? COLORS.green : data.xsect.current_regime === 'bearish' ? COLORS.red : COLORS.amber, marginLeft: 8 }}>
                  Regime: {data.xsect.current_regime?.toUpperCase()}
                </span>
              </div>

              {/* Liquidity Beta Table */}
              {data.xsect.beta_table?.length > 0 && (
                <div style={{ maxHeight: 200, overflowY: 'auto', marginBottom: 6 }}>
                  <table style={{ fontSize: 7, borderCollapse: 'collapse', width: '100%' }}>
                    <thead style={{ position: 'sticky', top: 0, background: '#0a0a0a' }}>
                      <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        {['TICKER', 'NAME', 'CLASS', 'β_LIQ', 'TYPE', 'STABILITY', 'STABLE'].map(h => (
                          <th key={h} style={{ textAlign: h === 'TICKER' || h === 'NAME' || h === 'CLASS' || h === 'TYPE' ? 'left' : 'right',
                            color: COLORS.textDim, padding: '1px 3px', fontSize: 7 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.xsect.beta_table.map(a => (
                        <tr key={a.ticker} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                          <td style={{ padding: '1px 3px', color: COLORS.white, fontWeight: 'bold' }}>{a.ticker}</td>
                          <td style={{ padding: '1px 3px', color: COLORS.textMuted, fontSize: 7 }}>{a.name}</td>
                          <td style={{ padding: '1px 3px', color: COLORS.textDim, fontSize: 6 }}>{a.asset_class}</td>
                          <td style={{ padding: '1px 3px', textAlign: 'right', color: a.beta_liq > 0 ? COLORS.green : a.beta_liq < -0.5 ? COLORS.red : COLORS.textMuted, fontWeight: 'bold' }}>
                            {a.beta_liq > 0 ? '+' : ''}{a.beta_liq}
                          </td>
                          <td style={{ padding: '1px 3px', color: a.classification === 'pro_liquidity' ? COLORS.green : a.classification === 'anti_liquidity' ? COLORS.red : COLORS.textDim, fontSize: 7 }}>
                            {a.classification === 'pro_liquidity' ? 'PRO' : a.classification === 'anti_liquidity' ? 'ANTI' : 'NEUT'}
                          </td>
                          <td style={{ padding: '1px 3px', textAlign: 'right', color: COLORS.textDim }}>{(a.stability * 100).toFixed(0)}%</td>
                          <td style={{ padding: '1px 3px', textAlign: 'right', color: a.stable ? COLORS.green : COLORS.red }}>{a.stable ? '✓' : '✗'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Portfolio Comparison */}
              {data.xsect.portfolio?.comparison?.length > 0 && (
                <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%', marginBottom: 6 }}>
                  <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {['VARIANT', 'SHARPE', 'SORTINO', 'DD', 'TOTAL RET', 'ANN VOL'].map(h => (
                      <th key={h} style={{ textAlign: h === 'VARIANT' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 4px', fontSize: 7 }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {data.xsect.portfolio.comparison.map((v, i) => (
                      <tr key={v.label} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                        background: i === 0 ? COLORS.textDim + '08' : 'none' }}>
                        <td style={{ padding: '2px 4px', color: COLORS.white, fontSize: 8 }}>{v.label}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.amber, fontWeight: 'bold' }}>{v.sharpe}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{v.sortino}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{v.max_dd}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.white }}>{v.total_return}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textDim }}>{v.ann_vol}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {/* Equity Curve */}
              {data.xsect.portfolio?.chart?.length > 0 && (
                <ResponsiveContainer width="100%" height={160}>
                  <ComposedChart data={data.xsect.portfolio.chart} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                    <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 7, fontFamily: FONT }} tickFormatter={d => d?.slice(0, 4)} interval="preserveStartEnd" />
                    <YAxis tick={{ fill: COLORS.textMuted, fontSize: 7, fontFamily: FONT }} tickFormatter={v => `${v?.toFixed(1)}x`} />
                    <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 8 }} />
                    <Line type="monotone" dataKey="long_only" stroke={COLORS.green} strokeWidth={2} dot={false} name="Long-Only" />
                    <Line type="monotone" dataKey="long_short" stroke={COLORS.cyan} strokeWidth={1.5} dot={false} name="Long/Short" />
                    <Line type="monotone" dataKey="spy_bh" stroke={COLORS.textDim} strokeWidth={1} strokeDasharray="3 3" dot={false} name="SPY B&H" />
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>
          )}
          {data?.xsect?.error && (
            <div style={S.card}>
              <div style={S.hdr}>CROSS-SECTIONAL — Error</div>
              <div style={{ color: COLORS.red, fontSize: 9 }}>{data.xsect.error}</div>
            </div>
          )}

          {/* Cross-Sectional Backtest + Leverage */}
          {data?.xsect_backtest && !data.xsect_backtest.error && (
            <div style={S.card}>
              <div style={S.hdr}>CROSS-SECTIONAL BACKTEST + CONDITIONAL LEVERAGE</div>
              {data.xsect_backtest.variants?.length > 0 && (
                <table style={{ fontSize: 7, borderCollapse: 'collapse', width: '100%' }}>
                  <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {['VARIANT', 'SHARPE', 'SORTINO', 'DD', 'CALMAR', 'RET', 'VOL', 'α(ann%)', 'β', 'LEV%'].map(h => (
                      <th key={h} style={{ textAlign: h === 'VARIANT' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 3px', fontSize: 6 }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {data.xsect_backtest.variants.map((v, i) => (
                      <tr key={v.label} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                        background: i === 0 ? COLORS.textDim + '08' : 'none' }}>
                        <td style={{ padding: '2px 3px', color: COLORS.white, fontSize: 7 }}>{v.label}</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.amber, fontWeight: 'bold' }}>{v.sharpe}</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>{v.sortino}</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.red }}>{v.max_dd}%</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>{v.calmar}</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.white }}>{v.total_return}%</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textDim }}>{v.ann_vol}%</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right',
                          color: v.capm_alpha?.alpha_annual_pct > 0 ? COLORS.green : v.capm_alpha?.alpha_annual_pct < 0 ? COLORS.red : COLORS.textDim }}>
                          {v.capm_alpha?.alpha_annual_pct != null ? `${v.capm_alpha.alpha_annual_pct > 0 ? '+' : ''}${v.capm_alpha.alpha_annual_pct}` : '--'}
                          {v.capm_alpha?.significant && ' *'}
                        </td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textDim }}>{v.capm_alpha?.beta ?? '--'}</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textDim }}>{v.pct_leveraged != null ? `${v.pct_leveraged}%` : '--'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div style={{ fontSize: 7, color: COLORS.textDim, marginTop: 3 }}>
                α = CAPM alpha (annualized %). * = significant (t-stat {'>'} 2). LEV% = time leveraged.
              </div>
            </div>
          )}

          {/* Real-Time Signal Validation */}
          {data?.realtime && !data.realtime.error && (
            <div style={S.card}>
              <div style={S.hdr}>REAL-TIME SIGNAL INTEGRITY — Publication Lag Simulation</div>

              {/* Verdict */}
              <div style={{ padding: '6px 10px', marginBottom: 8, background: '#0a0a0a',
                borderLeft: `3px solid ${data.realtime.forward_fill_safe ? COLORS.green : COLORS.red}`,
                fontSize: 10 }}>
                {data.realtime.verdict}
              </div>

              {/* Comparison table */}
              {data.realtime.comparison?.length > 0 && (
                <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%', marginBottom: 6 }}>
                  <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {['MODEL', 'SHARPE', 'SORTINO', 'MAX DD', 'TOTAL RET', 'CRASHES', 'LAGS'].map(h => (
                      <th key={h} style={{ textAlign: h === 'MODEL' || h === 'LAGS' ? 'left' : 'right',
                        color: COLORS.textDim, padding: '2px 4px', fontSize: 7 }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {data.realtime.comparison.map((r, i) => (
                      <tr key={r.model} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                        background: i === 0 ? COLORS.amber + '08' : 'none' }}>
                        <td style={{ padding: '2px 4px', color: i === 0 ? COLORS.amber : COLORS.white, fontSize: 8 }}>{r.model}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.amber, fontWeight: 'bold' }}>{r.sharpe}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{r.sortino}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{r.max_dd}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.white }}>{r.total_return}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right',
                          color: r.crashes?.startsWith('4') ? COLORS.green : COLORS.red }}>{r.crashes}</td>
                        <td style={{ padding: '2px 4px', color: COLORS.textDim, fontSize: 7 }}>{r.lags}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <div style={{ display: 'flex', gap: 16, fontSize: 8, color: COLORS.textDim }}>
                <span>Quintile agreement: <span style={{ color: COLORS.amber }}>{data.realtime.quintile_agreement_pct}%</span></span>
                <span>Signal correlation: <span style={{ color: COLORS.amber }}>{data.realtime.signal_correlation}</span></span>
                <span>Sharpe degradation: <span style={{ color: Math.abs(data.realtime.sharpe_degradation) < 0.1 ? COLORS.green : COLORS.red }}>
                  {data.realtime.sharpe_degradation > 0 ? '-' : '+'}{Math.abs(data.realtime.sharpe_degradation)}
                </span></span>
              </div>
            </div>
          )}
          {data?.realtime?.error && (
            <div style={S.card}>
              <div style={S.hdr}>REAL-TIME VALIDATION — Error</div>
              <div style={{ color: COLORS.red, fontSize: 9 }}>{data.realtime.error}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function DefensiveRotationPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    getDefensiveStudy().then(r => { if (r && !r.error) setData(r); }).catch(() => {});
  }, []);

  const run = async () => {
    setLoading(true);
    try { const r = await runDefensiveStudy(); if (r && !r.error) setData(r); }
    catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const S = { hdr: { color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 },
    card: { padding: '8px 12px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, marginBottom: 8 } };
  const gap = data?.integration?.gap_analysis;

  return (
    <div style={{ marginTop: 12 }}>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '▾' : '▸'} Defensive Rotation Study (What to Hold When Reducing Equity)
      </button>
      {expanded && (
        <div style={{ marginTop: 8, padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>DEFENSIVE ROTATION</span>
            <button onClick={run} disabled={loading}
              style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              {loading ? 'RUNNING (~2-3 MIN)...' : data ? 'RE-RUN' : 'RUN STUDY'}
            </button>
          </div>
          {!data && !loading && (
            <div style={{ color: COLORS.textDim, fontSize: 9 }}>
              Tests 17 defensive assets during GLI Q4/Q5 months. Builds optimal portfolio. Compares 4 rotation modes + regime-conditional with MC validation.
            </div>
          )}
          {gap && (
            <div style={{ padding: '8px 12px', marginBottom: 10, background: '#0a0a0a',
              borderLeft: `3px solid ${COLORS.green}`, fontSize: 11 }}>
              <span style={{ color: COLORS.textMuted }}>Return gap closed: </span>
              <span style={{ color: COLORS.green, fontWeight: 'bold', fontSize: 14 }}>{gap.gap_closed_pct}%</span>
              <span style={{ color: COLORS.textDim, fontSize: 9, marginLeft: 8 }}>
                ({gap.gap_closed}% of {gap.return_gap_cash}% gap vs B&H)
              </span>
            </div>
          )}
          {data?.screening?.assets?.length > 0 && (
            <div style={S.card}>
              <div style={S.hdr}>ASSET SCREENING (Q4/Q5 months, N={data.screening.n_defensive_months})</div>
              <div style={{ maxHeight: 220, overflowY: 'auto' }}>
                <table style={{ fontSize: 8, borderCollapse: 'collapse', width: '100%' }}>
                  <thead style={{ position: 'sticky', top: 0, background: '#0a0a0a' }}>
                    <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                      {['#', 'TICKER', 'SHARPE', 'RET', 'DD', 'SPX ρ', 'CRISIS α', 'SCORE'].map(h => (
                        <th key={h} style={{ textAlign: h === 'TICKER' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 3px', fontSize: 7 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.screening.assets.map((a, i) => (
                      <tr key={a.ticker} style={{ borderBottom: `1px solid ${COLORS.cardBorder}11`, background: i < 6 ? COLORS.green + '06' : 'none' }}>
                        <td style={{ padding: '2px 3px', color: COLORS.textDim }}>{i + 1}</td>
                        <td style={{ padding: '2px 3px', color: i < 6 ? COLORS.green : COLORS.white }}>{a.ticker}</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: a.sharpe_defensive > 0 ? COLORS.green : COLORS.red }}>{a.sharpe_defensive}</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.textMuted }}>{a.ann_return_defensive}%</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.red }}>{a.max_dd_defensive}%</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: Math.abs(a.spx_correlation) < 0.3 ? COLORS.green : COLORS.textMuted }}>{a.spx_correlation}</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: a.crisis_alpha > 0 ? COLORS.green : COLORS.red }}>{a.crisis_alpha}%</td>
                        <td style={{ padding: '2px 3px', textAlign: 'right', color: COLORS.amber, fontWeight: 'bold' }}>{a.defensive_score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {data?.portfolio?.optimized_weights && (
            <div style={S.card}>
              <div style={S.hdr}>OPTIMAL DEFENSIVE PORTFOLIO</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
                {Object.entries(data.portfolio.optimized_weights).map(([t, w]) => (
                  <span key={t} style={{ padding: '2px 6px', background: COLORS.green + '11', border: `1px solid ${COLORS.green}22`, fontSize: 9 }}>
                    <span style={{ color: COLORS.white }}>{t}</span> <span style={{ color: COLORS.green }}>{(w * 100).toFixed(0)}%</span>
                  </span>
                ))}
              </div>
              <div style={{ fontSize: 8, color: COLORS.textMuted }}>
                Sharpe: {data.portfolio.optimized?.sharpe} | SPX ρ: {data.portfolio.optimized?.spx_correlation} | DD: {data.portfolio.optimized?.max_dd}%
              </div>
            </div>
          )}
          {data?.integration?.modes && (
            <div style={S.card}>
              <div style={S.hdr}>ROTATION MODE COMPARISON</div>
              <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['MODE', 'TOTAL', 'SHARPE', 'DD', 'CALMAR', 'GAP'].map(h => (
                    <th key={h} style={{ textAlign: h === 'MODE' ? 'left' : 'right', color: COLORS.textDim, padding: '2px 4px', fontSize: 8 }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {Object.values(data.integration.modes).map(m => {
                    const best = Object.values(data.integration.modes).reduce((a, b) => (a.sharpe || 0) > (b.sharpe || 0) ? a : b);
                    return (
                      <tr key={m.name} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`, background: m.sharpe === best.sharpe ? COLORS.green + '11' : 'none' }}>
                        <td style={{ padding: '2px 4px', color: m.sharpe === best.sharpe ? COLORS.green : COLORS.white, fontSize: 8 }}>{m.sharpe === best.sharpe ? '★ ' : ''}{m.name}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.white }}>{m.total_return}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.amber }}>{m.sharpe}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.red }}>{m.max_dd}%</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textMuted }}>{m.calmar}</td>
                        <td style={{ padding: '2px 4px', textAlign: 'right', color: COLORS.textDim }}>{m.return_gap_vs_bh}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {data?.integration?.chart?.length > 0 && (
            <div style={S.card}>
              <div style={S.hdr}>EQUITY CURVES</div>
              <ResponsiveContainer width="100%" height={180}>
                <ComposedChart data={data.integration.chart} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                  <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 7, fontFamily: FONT }} tickFormatter={d => d?.slice(0, 4)} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: COLORS.textMuted, fontSize: 8, fontFamily: FONT }} tickFormatter={v => `${v?.toFixed(1)}x`} />
                  <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 9 }} />
                  <Line type="monotone" dataKey="cash" stroke={COLORS.red} strokeWidth={1.5} dot={false} name="Cash Default" />
                  <Line type="monotone" dataKey="defensive" stroke={COLORS.green} strokeWidth={2} dot={false} name="Defensive" />
                  <Line type="monotone" dataKey="buyhold" stroke={COLORS.textDim} strokeWidth={1} strokeDasharray="4 2" dot={false} name="B&H" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
          {data?.regime && !data.regime.error && (
            <div style={S.card}>
              <div style={S.hdr}>REGIME-CONDITIONAL DEFENSIVE</div>
              <div style={{ fontSize: 9, marginBottom: 4 }}>
                <span style={{ color: COLORS.textMuted }}>Current: </span>
                <span style={{ color: COLORS.amber }}>{data.regime.current_regime?.toUpperCase()}</span>
                <span style={{ color: COLORS.textMuted, marginLeft: 8 }}>RC Sharpe: </span>
                <span style={{ color: COLORS.amber }}>{data.regime.regime_conditional?.sharpe}</span>
                <span style={{ color: COLORS.textMuted }}> vs Static: </span>
                <span style={{ color: COLORS.textDim }}>{data.regime.static_defensive?.sharpe}</span>
              </div>
              <div style={{ fontSize: 9, color: data.regime.significant ? COLORS.green : COLORS.red,
                borderLeft: `3px solid ${data.regime.significant ? COLORS.green : COLORS.red}`, paddingLeft: 8 }}>
                {data.regime.significant
                  ? `SIGNIFICANT (p=${data.regime.monte_carlo?.p_value?.toFixed(4)})`
                  : `NOT significant (p=${data.regime.monte_carlo?.p_value?.toFixed(4)}) — use static defensive`}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
