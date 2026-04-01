import React, { useState, useMemo } from 'react';
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getEquity, optimizePortfolio } from '../utils/api';

const NUM_TO_RATING = {1:'AAA',2:'AA+',3:'AA',4:'AA-',5:'A+',6:'A',7:'A-',8:'BBB+',9:'BBB',10:'BBB-',11:'BB+',12:'BB',13:'BB-',14:'B+',15:'B',16:'B-',17:'CCC+',18:'CCC',19:'CCC-',20:'CC',21:'C',22:'D'};
const PIE_COLORS = [COLORS.amber, COLORS.cyan, COLORS.green, COLORS.purple, COLORS.red, COLORS.blue, COLORS.pink, '#ff9100'];

export default function PortfolioConstruction({ portfolio, setPortfolio, clientSettings, onAddEquity }) {
  const [equityTicker, setEquityTicker] = useState('');
  const [equityLoading, setEquityLoading] = useState(false);
  const [equityError, setEquityError] = useState('');
  const [optLoading, setOptLoading] = useState(false);
  const [optError, setOptError] = useState('');
  const [showOptSettings, setShowOptSettings] = useState(false);
  const [excludedIds, setExcludedIds] = useState([]);
  const [optConstraints, setOptConstraints] = useState({
    target_duration: 3.0, max_issuer_pct: 0.05, max_position_pct: 0.10,
    max_usd_pct: 0.50, min_rating_num: 13, max_positions: 20,
    weights: { ytm: 0.30, default: 0.25, spread_eff: 0.25, icr: 0.10, ebitda: 0.10 },
  });

  const handleOptimize = async () => {
    setOptLoading(true);
    setOptError('');
    try {
      const fees = clientSettings.fees || {};
      const annFees = (fees.management || 0) + (fees.custody || 0);
      const grossTarget = (clientSettings.targetReturn || 5.5) + annFees;
      const result = await optimizePortfolio({
        ...optConstraints,
        investment_amount: clientSettings.investmentAmount || 200000,
        target_return: grossTarget,
        excluded_ids: excludedIds,
      });
      if (result.positions?.length > 0) {
        setPortfolio(result.positions);
      } else {
        setOptError(result.error || 'No eligible bonds found');
      }
    } catch (e) {
      setOptError(e.message);
    } finally {
      setOptLoading(false);
    }
  };

  const totalAllocation = useMemo(() => portfolio.reduce((s, p) => s + (p.allocation || 0), 0), [portfolio]);

  const bonds = useMemo(() => portfolio.filter(p => p.asset_class || p.ytm != null), [portfolio]);
  const equities = useMemo(() => portfolio.filter(p => p.trailing_3y_return != null || p.dividend_yield != null), [portfolio]);
  const bondTotal = useMemo(() => bonds.reduce((s, p) => s + (p.allocation || 0), 0), [bonds]);
  const eqTotal = useMemo(() => equities.reduce((s, p) => s + (p.allocation || 0), 0), [equities]);

  // Weighted average helper — excludes nulls
  const wavg = (items, field, weightField = 'allocation') => {
    let sumW = 0, sumWV = 0;
    items.forEach(item => {
      const v = item[field];
      const w = item[weightField] || 0;
      if (v != null && w > 0) { sumW += w; sumWV += w * v; }
    });
    return sumW > 0 ? sumWV / sumW : null;
  };

  // Fixed income metrics
  const fiMetrics = useMemo(() => {
    if (bonds.length === 0) return null;
    const wYtm = wavg(bonds, 'ytm');
    const wCpn = wavg(bonds, 'coupon');
    const wDur = wavg(bonds, 'duration');
    const wOas = wavg(bonds, 'oas_spread');
    const wGsp = wavg(bonds, 'g_spread');
    const wRat = wavg(bonds, 'rating_num');
    const wDp = wavg(bonds, 'default_probability');
    const annualIncome = bonds.reduce((s, b) => s + (b.coupon || 0) / 100 * (b.allocation || 0), 0);
    return { wYtm, wCpn, wDur, wOas, wGsp, wRat, wDp, annualIncome,
      ratingLabel: wRat ? NUM_TO_RATING[Math.round(wRat)] || `~${wRat.toFixed(1)}` : '—' };
  }, [bonds]);

  // Fees
  const fees = clientSettings.fees || {};
  const annualFees = (fees.management || 0) + (fees.custody || 0);
  const formationFee = fees.formation || 0;
  const grossTarget = (clientSettings.targetReturn || 5.5) + annualFees;

  // Combined expected return
  const combinedReturn = useMemo(() => {
    if (totalAllocation === 0) return null;
    const bondReturn = fiMetrics?.wYtm || 0;
    const eqReturn = equities.length > 0 ? wavg(equities, 'expected_return') || 0 : 0;
    return (bondTotal / totalAllocation * bondReturn + eqTotal / totalAllocation * eqReturn);
  }, [fiMetrics, equities, bondTotal, eqTotal, totalAllocation]);

  const surplus = combinedReturn != null ? (combinedReturn - grossTarget) * 100 : null; // in bp

  // Diversification data
  const currencyData = useMemo(() => {
    const map = {};
    portfolio.forEach(p => { const c = p.currency || 'Other'; map[c] = (map[c] || 0) + (p.allocation || 0); });
    return Object.entries(map).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  }, [portfolio]);

  const ratingData = useMemo(() => {
    const buckets = { 'AAA-A': 0, 'BBB': 0, 'BB': 0, 'B & below': 0, 'NR': 0 };
    bonds.forEach(b => {
      const rn = b.rating_num;
      const a = b.allocation || 0;
      if (rn == null) buckets['NR'] += a;
      else if (rn <= 7) buckets['AAA-A'] += a;
      else if (rn <= 10) buckets['BBB'] += a;
      else if (rn <= 13) buckets['BB'] += a;
      else buckets['B & below'] += a;
    });
    return Object.entries(buckets).filter(([, v]) => v > 0).map(([name, value]) => ({ name, value }));
  }, [bonds]);

  const maturityData = useMemo(() => {
    const years = {};
    bonds.forEach(b => {
      const ytm = b.years_to_maturity;
      if (ytm != null) {
        const bucket = Math.ceil(ytm);
        const label = `${bucket}Y`;
        years[label] = (years[label] || 0) + (b.allocation || 0);
      }
    });
    return Object.entries(years).sort((a, b) => parseInt(a[0]) - parseInt(b[0])).map(([name, value]) => ({ name, value }));
  }, [bonds]);

  const issuerData = useMemo(() => {
    const map = {};
    portfolio.forEach(p => { const n = p.issuer_name || p.name || p.ticker || 'Unknown'; map[n] = (map[n] || 0) + (p.allocation || 0); });
    return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([name, value]) => ({
      name: name.length > 20 ? name.slice(0, 18) + '…' : name, value,
      pct: totalAllocation > 0 ? (value / totalAllocation * 100) : 0,
      warning: totalAllocation > 0 && (value / totalAllocation) > 0.05,
    }));
  }, [portfolio, totalAllocation]);

  const handleAddEquity = async () => {
    if (!equityTicker) return;
    setEquityLoading(true);
    setEquityError('');
    try {
      const eq = await getEquity(equityTicker);
      const item = {
        id: `EQ_${eq.ticker}`,
        issuer_name: eq.name,
        ticker: eq.ticker,
        currency: eq.currency,
        dividend_yield: eq.dividend_yield,
        beta: eq.beta,
        pe_ratio: eq.pe_ratio,
        sector: eq.sector,
        price: eq.price,
        trailing_3y_return: eq.trailing_3y_return,
        expected_return: (eq.dividend_yield || 0) + (eq.trailing_3y_return || 5),
        type: 'equity',
        allocation: 10000,
      };
      onAddEquity(item);
      setEquityTicker('');
    } catch (e) {
      setEquityError(e.message);
    } finally {
      setEquityLoading(false);
    }
  };

  const removeItem = (id) => {
    setPortfolio(prev => prev.filter(p => p.id !== id));
    setExcludedIds(prev => [...new Set([...prev, id])]);
  };
  const updateAlloc = (id, val) => setPortfolio(prev => prev.map(p => p.id === id ? { ...p, allocation: parseFloat(val) || 0 } : p));

  const metricBox = (label, value, unit = '', warn = false) => (
    <div style={{ padding: '6px 10px', background: COLORS.bgDark, minWidth: 100, textAlign: 'center' }}>
      <div style={{ fontSize: 9, color: COLORS.textMuted, marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 'bold', color: warn ? COLORS.red : COLORS.amber }}>
        {value ?? '—'}{unit}
      </div>
    </div>
  );

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white }}>
      {/* Target return tracker */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '10px 12px',
        background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: COLORS.textMuted }}>TARGET NET:</div>
        <div style={{ fontSize: 18, fontWeight: 'bold', color: COLORS.amber }}>{clientSettings.targetReturn}%</div>
        <div style={{ fontSize: 9, color: COLORS.textMuted }}>(gross {grossTarget.toFixed(1)}%)</div>
        <div style={{ width: 1, height: 24, background: COLORS.cardBorder, margin: '0 8px' }} />
        <div style={{ fontSize: 11, color: COLORS.textMuted }}>CURRENT:</div>
        <div style={{ fontSize: 18, fontWeight: 'bold', color: combinedReturn != null ? (surplus >= 0 ? COLORS.green : surplus > -50 ? COLORS.amber : COLORS.red) : COLORS.textMuted }}>
          {combinedReturn != null ? combinedReturn.toFixed(2) + '%' : '—'}
        </div>
        {surplus != null && (
          <div style={{ fontSize: 11, color: surplus >= 0 ? COLORS.green : COLORS.red, fontWeight: 'bold' }}>
            {surplus >= 0 ? '+' : ''}{surplus.toFixed(0)}bp
          </div>
        )}
        <div style={{ width: 1, height: 24, background: COLORS.cardBorder, margin: '0 8px' }} />
        <div style={{ fontSize: 11, color: COLORS.textMuted }}>DURATION:</div>
        <div style={{ fontSize: 18, fontWeight: 'bold', color: fiMetrics?.wDur > 3.5 ? COLORS.red : COLORS.amber }}>
          {fiMetrics?.wDur?.toFixed(1) ?? '—'}
        </div>
        {fiMetrics?.wDur > 3.5 && <div style={{ fontSize: 9, color: COLORS.red }}>⚠ &gt;3.5</div>}
        <div style={{ width: 1, height: 24, background: COLORS.cardBorder, margin: '0 8px' }} />
        <div style={{ fontSize: 11, color: COLORS.textMuted }}>POSITIONS:</div>
        <div style={{ fontSize: 14, color: COLORS.white }}>{bonds.length}B + {equities.length}E</div>
        <div style={{ fontSize: 11, color: COLORS.textMuted, marginLeft: 'auto' }}>
          TOTAL: €{totalAllocation.toLocaleString()}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Left: Portfolio basket */}
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: COLORS.amber }}>PORTFOLIO POSITIONS</span>
            <div style={{ display: 'flex', gap: 4 }}>
              <button onClick={handleOptimize} disabled={optLoading}
                style={{ padding: '3px 10px', background: COLORS.green, color: COLORS.bg,
                  border: 'none', fontFamily: FONT, fontSize: 10, cursor: 'pointer',
                  opacity: optLoading ? 0.5 : 1 }}>
                {optLoading ? 'OPTIMIZING...' : '⚡ OPTIMIZE'}
              </button>
              <button onClick={() => setShowOptSettings(!showOptSettings)}
                style={{ padding: '3px 8px', background: 'none', color: COLORS.textMuted,
                  border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
                {showOptSettings ? '▲' : '⚙'}
              </button>
            </div>
          </div>
          {optError && <div style={{ color: COLORS.red, fontSize: 10, marginBottom: 4 }}>{optError}</div>}

          {/* Optimizer settings (collapsible) */}
          {showOptSettings && (
            <div style={{ background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, padding: 10, marginBottom: 8, fontSize: 10 }}>
              <div style={{ color: COLORS.amber, fontSize: 9, marginBottom: 6, letterSpacing: 1 }}>OPTIMIZER CONSTRAINTS</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                {[
                  ['Max Duration', 'target_duration', optConstraints.target_duration],
                  ['Max Positions', 'max_positions', optConstraints.max_positions],
                  ['Max Issuer %', 'max_issuer_pct', (optConstraints.max_issuer_pct * 100)],
                  ['Max Position %', 'max_position_pct', (optConstraints.max_position_pct * 100)],
                  ['Max USD %', 'max_usd_pct', (optConstraints.max_usd_pct * 100)],
                  ['Min Rating (num)', 'min_rating_num', optConstraints.min_rating_num],
                ].map(([label, key, val]) => (
                  <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ color: COLORS.textMuted, width: 90, fontSize: 9 }}>{label}</span>
                    <input type="number" step="0.1" value={val}
                      onChange={e => {
                        const v = parseFloat(e.target.value) || 0;
                        const actual = key.includes('pct') ? v / 100 : v;
                        setOptConstraints(prev => ({ ...prev, [key]: actual }));
                      }}
                      style={{ width: 50, padding: '2px 4px', background: COLORS.bg, border: `1px solid ${COLORS.cardBorder}`,
                        color: COLORS.white, fontFamily: FONT, fontSize: 10, outline: 'none' }} />
                  </div>
                ))}
              </div>
              <div style={{ color: COLORS.amber, fontSize: 9, marginTop: 6, marginBottom: 4 }}>SCORE WEIGHTS</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {[['YTM', 'ytm'], ['Default', 'default'], ['Spread/Dur', 'spread_eff'], ['ICR', 'icr'], ['EBITDA', 'ebitda']].map(([label, key]) => (
                  <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <span style={{ color: COLORS.textMuted, fontSize: 8 }}>{label}</span>
                    <input type="number" step="0.05" value={optConstraints.weights[key]}
                      onChange={e => setOptConstraints(prev => ({
                        ...prev, weights: { ...prev.weights, [key]: parseFloat(e.target.value) || 0 }
                      }))}
                      style={{ width: 40, padding: '2px', background: COLORS.bg, border: `1px solid ${COLORS.cardBorder}`,
                        color: COLORS.white, fontFamily: FONT, fontSize: 9, outline: 'none' }} />
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 6, display: 'flex', gap: 4 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 4, color: COLORS.textMuted, fontSize: 9, cursor: 'pointer' }}>
                  <input type="checkbox" checked={excludedIds.length > 0}
                    onChange={() => setExcludedIds([])} />
                  Clear excluded bonds ({excludedIds.length})
                </label>
              </div>
            </div>
          )}

          {portfolio.length > 0 && portfolio[0]._score != null && (
            <div style={{ fontSize: 9, color: COLORS.amber, padding: '4px 0', marginBottom: 4, borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
              ⚡ SUGGESTED ALLOCATION — review and adjust before use
            </div>
          )}
          {/* Add equity */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
            <input value={equityTicker} onChange={e => setEquityTicker(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && handleAddEquity()}
              placeholder="Add equity ticker..."
              style={{ flex: 1, padding: '4px 8px', background: COLORS.bg, border: `1px solid ${COLORS.cardBorder}`,
                color: COLORS.white, fontFamily: FONT, fontSize: 11, outline: 'none' }} />
            <button onClick={handleAddEquity} disabled={equityLoading}
              style={{ padding: '4px 12px', background: COLORS.cyan, color: COLORS.bg, border: 'none',
                fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              {equityLoading ? '...' : 'ADD'}
            </button>
          </div>
          {equityError && <div style={{ color: COLORS.red, fontSize: 10, marginBottom: 4 }}>{equityError}</div>}

          {/* Position list */}
          <div style={{ maxHeight: 400, overflowY: 'auto' }}>
            {portfolio.map(p => (
              <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0',
                borderBottom: `1px solid ${COLORS.cardBorder}22`, fontSize: 10 }}>
                <span style={{ color: p.type === 'equity' ? COLORS.cyan : COLORS.amber, fontSize: 8, width: 14 }}>
                  {p.type === 'equity' ? 'EQ' : 'FI'}
                </span>
                <span style={{ flex: 1, color: COLORS.white, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.issuer_name || p.name || p.ticker}
                </span>
                <span style={{ color: COLORS.textMuted, width: 35 }}>{p.currency}</span>
                <span style={{ color: COLORS.textMuted, width: 40 }}>{p.ytm ? p.ytm.toFixed(1) + '%' : p.dividend_yield ? p.dividend_yield.toFixed(1) + '%' : ''}</span>
                {p._score != null && <span style={{ color: COLORS.green, width: 30, fontSize: 8 }}>{p._score.toFixed(2)}</span>}
                <input value={p.allocation} onChange={e => updateAlloc(p.id, e.target.value)}
                  style={{ width: 65, padding: '2px 4px', background: COLORS.bg, border: `1px solid ${COLORS.cardBorder}`,
                    color: COLORS.white, fontFamily: FONT, fontSize: 10, textAlign: 'right', outline: 'none' }} />
                <button onClick={() => removeItem(p.id)} style={{
                  background: 'none', border: 'none', color: COLORS.red, cursor: 'pointer', fontSize: 12 }}>×</button>
              </div>
            ))}
            {portfolio.length === 0 && <div style={{ color: COLORS.textMuted, fontSize: 11, padding: 20, textAlign: 'center' }}>
              No positions. Add bonds from the Screener or equities above.
            </div>}
          </div>
        </div>

        {/* Right: Metrics */}
        <div>
          {/* FI metrics */}
          {fiMetrics && (
            <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12, marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8 }}>FIXED INCOME METRICS</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {metricBox('W.AVG YTM', fiMetrics.wYtm?.toFixed(2), '%')}
                {metricBox('W.AVG CPN', fiMetrics.wCpn?.toFixed(2), '%')}
                {metricBox('W.AVG DUR', fiMetrics.wDur?.toFixed(1), '', fiMetrics.wDur > 3.5)}
                {metricBox('W.AVG OAS', fiMetrics.wOas?.toFixed(0), 'bp')}
                {metricBox('RATING', fiMetrics.ratingLabel)}
                {metricBox('DEF PROB', fiMetrics.wDp ? (fiMetrics.wDp * 100).toFixed(2) + '%' : '—')}
                {metricBox('ANN INCOME', '€' + fiMetrics.annualIncome.toLocaleString(undefined, { maximumFractionDigits: 0 }))}
              </div>
            </div>
          )}

          {/* Asset split warning */}
          {eqTotal > 0 && totalAllocation > 0 && (
            <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12, marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 4 }}>ASSET SPLIT</div>
              <div style={{ display: 'flex', gap: 12, fontSize: 12 }}>
                <span>Bonds: {(bondTotal / totalAllocation * 100).toFixed(0)}%</span>
                <span style={{ color: (eqTotal / totalAllocation) > 0.2 ? COLORS.red : COLORS.white }}>
                  Equities: {(eqTotal / totalAllocation * 100).toFixed(0)}%
                  {(eqTotal / totalAllocation) > 0.2 && ' ⚠ >20%'}
                </span>
              </div>
            </div>
          )}

          {/* Charts */}
          {portfolio.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {/* Currency */}
              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 8 }}>
                <div style={{ fontSize: 9, color: COLORS.amber, marginBottom: 4 }}>CURRENCY</div>
                <ResponsiveContainer width="100%" height={120}>
                  <PieChart>
                    <Pie data={currencyData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={45} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`} labelLine={false} style={{ fontSize: 9 }}>
                      {currencyData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
              {/* Rating */}
              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 8 }}>
                <div style={{ fontSize: 9, color: COLORS.amber, marginBottom: 4 }}>RATING DISTRIBUTION</div>
                <ResponsiveContainer width="100%" height={120}>
                  <BarChart data={ratingData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                    <XAxis dataKey="name" tick={{ fill: COLORS.textMuted, fontSize: 8 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: COLORS.textMuted, fontSize: 8 }} axisLine={false} tickLine={false} tickFormatter={v => `${(v/1000).toFixed(0)}k`} />
                    <Bar dataKey="value" fill={COLORS.amber} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {/* Maturity ladder */}
              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 8 }}>
                <div style={{ fontSize: 9, color: COLORS.amber, marginBottom: 4 }}>MATURITY LADDER</div>
                <ResponsiveContainer width="100%" height={120}>
                  <BarChart data={maturityData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                    <XAxis dataKey="name" tick={{ fill: COLORS.textMuted, fontSize: 8 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: COLORS.textMuted, fontSize: 8 }} axisLine={false} tickLine={false} tickFormatter={v => `${(v/1000).toFixed(0)}k`} />
                    <Bar dataKey="value" fill={COLORS.cyan} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {/* Issuer concentration */}
              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 8 }}>
                <div style={{ fontSize: 9, color: COLORS.amber, marginBottom: 4 }}>TOP ISSUERS</div>
                <div style={{ fontSize: 9 }}>
                  {issuerData.map(d => (
                    <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
                      <div style={{ flex: 1, height: 8, background: COLORS.bgDark }}>
                        <div style={{ height: '100%', width: `${d.pct}%`, background: d.warning ? COLORS.red : COLORS.green }} />
                      </div>
                      <span style={{ color: d.warning ? COLORS.red : COLORS.textMuted, width: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {d.name} {d.pct.toFixed(0)}%{d.warning ? ' ⚠' : ''}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
