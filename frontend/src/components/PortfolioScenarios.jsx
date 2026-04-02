import React, { useState, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, ReferenceLine, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import { COLORS, FONT } from '../utils/theme';

// Rating-specific default rates and recovery rates (Moody's/S&P historical calibration)
const RATING_DEFAULTS = {
  IG_HIGH: [0.0005, 0.55],  // AAA/AA/A: 0.05% base default, 55% recovery
  IG_LOW:  [0.0020, 0.45],  // BBB: 0.20% base default, 45% recovery
  HY_BB:   [0.0080, 0.35],  // BB: 0.80% base default, 35% recovery
  HY_B:    [0.0300, 0.30],  // B: 3.00% base default, 30% recovery
  HY_CCC:  [0.1500, 0.20],  // CCC+: 15.00% base default, 20% recovery
};

function getRatingBucket(ratingNum) {
  if (ratingNum == null) return 'HY_BB'; // unknown defaults to BB
  if (ratingNum <= 7) return 'IG_HIGH';
  if (ratingNum <= 10) return 'IG_LOW';
  if (ratingNum <= 13) return 'HY_BB';
  if (ratingNum <= 16) return 'HY_B';
  return 'HY_CCC';
}

const METHODOLOGY = {
  'RATE SCENARIOS': {
    title: 'Rate Scenario Methodology',
    formula: '≤100bp: Price Chg = -Duration × ΔYield × 100\n>100bp: Price Chg = (-Duration × ΔYield + 0.5 × Convexity × ΔYield²) × 100',
    explanation: [
      'Models the impact of parallel interest rate shifts on bond prices.',
      'For rate moves ≤ 100bp, uses linear duration approximation (standard industry approach).',
      'For rate moves > 100bp, applies a convexity adjustment. Bonds have positive convexity — prices fall less than duration predicts for large rate increases, and rise more for large rate decreases.',
      'Convexity is estimated as Duration² × 0.5 when not provided in the data.',
      'Each bond is calculated individually and allocation-weighted, not using portfolio averages.',
      'Assumes a parallel shift across the entire yield curve (all maturities move equally).',
    ],
    example: (dur) => {
      const cvx = dur * dur * 0.5;
      const dy = 0.015;
      const linear = (-dur * dy * 100).toFixed(2);
      const withCvx = ((-dur * dy + 0.5 * cvx * dy * dy) * 100).toFixed(2);
      return `Duration ${dur.toFixed(1)}, Rates +150bp → Linear: ${linear}% | With convexity: ${withCvx}% (less negative)`;
    },
  },
  'SPREAD SCENARIOS': {
    title: 'Spread Scenario Methodology',
    formula: 'Price Chg = -Duration × ΔSpread × 100 (dampened for large moves)',
    explanation: [
      'Models credit spread widening/tightening impact on bond prices.',
      'Uses the same duration sensitivity as rate scenarios — OAS spread changes affect bond prices identically to rate changes.',
      'Spread widening (positive ΔSpread) = bond prices fall (credit risk repricing).',
      'Spread tightening (negative ΔSpread) = bond prices rise (improving credit conditions).',
      'Large spread scenarios include a dampening factor reflecting historical mean-reversion tendency:',
      '• +200bp: 0.95× multiplier (distressed buyers provide some price support)',
      '• +300bp+: 0.90× multiplier (extreme moves trigger value-seeking flows)',
    ],
    example: (dur) => `Duration ${dur.toFixed(1)}, OAS +200bp → -${dur.toFixed(1)} × 0.02 × 100 × 0.95 = ${(-dur * 0.02 * 100 * 0.95).toFixed(2)}%`,
  },
  'DEFAULT SCENARIOS': {
    title: 'Default Scenario Methodology',
    formula: 'Per-bond loss = Rating Default Rate × Multiplier × (1 - Recovery Rate)',
    explanation: [
      'Uses rating-specific default rates calibrated to historical Moody\'s/S&P default studies:',
      '',
      '• AAA/AA/A: 0.05% base default rate, 55% recovery',
      '• BBB: 0.20% base default rate, 45% recovery',
      '• BB: 0.80% base default rate, 35% recovery',
      '• B: 3.00% base default rate, 30% recovery',
      '• CCC and below: 15.00% base default rate, 20% recovery',
      '',
      'Scenario multiplier scales the base rate: 1× (base), 1.5× (mild recession), 3× (severe recession).',
      'Each bond is assessed individually based on its rating — HY-heavy portfolios face higher default losses than IG portfolios.',
      'Recovery rates are also rating-specific, reflecting that lower-rated issuers typically have lower recovery in default.',
    ],
    example: () => 'BBB bond, 1.5× multiplier: 0.20% × 1.5 × (1 - 45%) = 0.165% loss contribution',
  },
  'FX SCENARIOS': {
    title: 'FX Scenario Methodology',
    formula: 'FX Impact % = -EUR/USD Change % × USD Allocation %',
    explanation: [
      'Models currency risk for a EUR-based investor holding USD-denominated bonds.',
      'Applied ONLY to the USD portion of the portfolio — EUR bonds have no FX exposure.',
      'EUR strengthening (EUR/USD rises, e.g., +5%) = negative for USD bond holders (USD buys fewer EUR when converting back).',
      'EUR weakening (EUR/USD falls, e.g., -5%) = positive for USD bond holders.',
      'The impact is proportional to how much of the portfolio is in USD.',
      'Does not account for FX hedging — if bonds are hedged, actual FX impact would be near zero but hedging costs apply.',
    ],
    example: (usdPct) => `EUR/USD +5%, USD allocation ${(usdPct * 100).toFixed(0)}% → -5% × ${(usdPct * 100).toFixed(0)}% = ${(-5 * usdPct).toFixed(2)}% impact`,
  },
  'EQUITY SCENARIOS': {
    title: 'Equity Scenario Methodology',
    formula: 'Equity Impact = Market Chg × Beta × Eq Alloc% + Correlation Spread Stress',
    explanation: [
      'Models equity market drawdown impact on the equity portion of the portfolio.',
      'Uses the weighted average portfolio beta to estimate sensitivity to market moves.',
      'Beta = 1.0 means the equity moves in line with the market. Beta > 1 = more volatile, < 1 = less volatile.',
      '',
      'Severe equity scenarios include estimated credit spread contagion:',
      '• Market -20% or worse: auto-adds +50bp spread widening to bond sleeve',
      '• Market -30% or worse: auto-adds +100bp spread widening to bond sleeve',
      '',
      'This reflects the empirical observation that in severe equity selloffs, credit spreads widen simultaneously (flight from risk). HY bonds cannot be used as a safe haven during equity crashes.',
    ],
    example: (beta, eqPct) => `Market -20%, Beta ${beta.toFixed(2)}, Eq ${(eqPct * 100).toFixed(0)}% → equity: ${(-20 * beta * eqPct).toFixed(2)}% + credit contagion: +50bp spread widening on bonds`,
  },
  'LIQUIDITY STRESS': {
    title: 'Liquidity Stress Methodology',
    formula: 'Liquidation Cost = Σ (Bond Bid-Ask × Stress Multiplier × Bond Weight)',
    explanation: [
      'Models the cost of forced portfolio liquidation in stressed markets.',
      'Uses each bond\'s actual bid-ask spread from market data, multiplied by a stress factor:',
      '• Mild stress: 3× normal bid-ask (moderate market dysfunction)',
      '• Severe stress: 5× normal bid-ask (market seizure, limited buyers)',
      '',
      'The most illiquid positions (widest bid-ask) are highlighted below the table.',
      'In practice, liquidation costs can exceed these estimates for very large positions or illiquid markets.',
      'Bonds are ranked from most to least liquid to help identify exit risk concentrations.',
    ],
    example: () => 'Bond with 0.40 bid-ask, severe stress: 0.40 × 5 / 100 = 2.00% liquidation cost for that position',
  },
  'COMBINED STRESS': {
    title: 'Combined Stress Scenario Methodology',
    formula: 'Total = Rate + Spread + Defaults + FX + Equity + Correlation Stress',
    explanation: [
      'Applies multiple shocks simultaneously to model realistic macro scenarios:',
      '',
      'Mild recession: Rates -50bp, Spreads +100bp, Rating-sensitive defaults (1.5×), Equities -15%, EUR/USD +5%',
      'Severe recession: Rates -100bp, Spreads +200bp, Defaults (3×), Equities -30%, EUR/USD +10% + correlation spread stress',
      'Inflation shock: Rates +150bp (with convexity), Spreads +50bp, Equities -10%, EUR/USD -5%',
      'Soft landing: Rates -50bp, Spreads -50bp, Equities +10%',
      '',
      'Combined scenarios include all enhanced methodologies: convexity for large rate moves, spread dampening, rating-sensitive defaults, and equity-credit correlation stress.',
    ],
    example: () => 'Severe recession: rate (convexity-adjusted) + spread (dampened) + defaults (rating-specific) + FX + equity + correlation stress',
  },
};

const COLUMNS_INFO = {
  title: 'Column Definitions',
  items: [
    ['PRICE CHG %', 'Change in portfolio market value from the scenario shock. Negative = portfolio loses value.'],
    ['INCOME €', 'Annual coupon income (bonds) + dividend income (equities). Constant across scenarios — assumes no defaults affect coupon payments.'],
    ['GROSS RETURN %', 'Price Change + Base Expected Return (weighted YTM for bonds + expected return for equities). Before fees.'],
    ['NET RETURN %', 'Gross Return - Annual Fees (management + custody) - Formation Fee. This is the investor\'s actual return. Green = meets target, Red = below target.'],
    ['RECOVERY (mo)', 'Months to recover the price loss from coupon/dividend income alone. |Price Loss| ÷ (Monthly Income as % of portfolio). Green < 6 months, Amber 6-12 months, Red > 12 months. Dash for gains.'],
  ],
};

export default function PortfolioScenarios({ portfolio, clientSettings }) {
  const [showInfo, setShowInfo] = useState(null);

  const fees = clientSettings.fees || {};
  const annualFees = (fees.management || 0) + (fees.custody || 0);
  const formationFee = fees.formation || 0;
  const targetNet = clientSettings.targetReturn || 5.5;

  const bonds = useMemo(() => portfolio.filter(p => p.ytm != null), [portfolio]);
  const equities = useMemo(() => portfolio.filter(p => p.type === 'equity'), [portfolio]);
  const totalAlloc = useMemo(() => portfolio.reduce((s, p) => s + (p.allocation || 0), 0), [portfolio]);
  const bondAlloc = useMemo(() => bonds.reduce((s, p) => s + (p.allocation || 0), 0), [bonds]);
  const eqAlloc = useMemo(() => equities.reduce((s, p) => s + (p.allocation || 0), 0), [equities]);
  const usdBondAlloc = useMemo(() => bonds.filter(b => b.currency === 'USD').reduce((s, b) => s + (b.allocation || 0), 0), [bonds]);

  const wavg = (items, field) => {
    let sw = 0, swv = 0;
    items.forEach(i => { const v = i[field], w = i.allocation || 0; if (v != null && w > 0) { sw += w; swv += w * v; } });
    return sw > 0 ? swv / sw : 0;
  };

  const wDur = wavg(bonds, 'duration');
  const wYtm = wavg(bonds, 'ytm');
  const wOas = wavg(bonds, 'oas_spread');
  const wBeta = wavg(equities, 'beta') || 1;
  const eqExpRet = wavg(equities, 'expected_return');
  const annualIncome = bonds.reduce((s, b) => s + (b.coupon || 0) / 100 * (b.allocation || 0), 0) +
    equities.reduce((s, e) => s + (e.dividend_yield || 0) / 100 * (e.allocation || 0), 0);
  const baseReturn = totalAlloc > 0 ? (bondAlloc / totalAlloc * wYtm + eqAlloc / totalAlloc * eqExpRet) : 0;
  const usdPct = totalAlloc > 0 ? usdBondAlloc / totalAlloc : 0;
  const eqPct = totalAlloc > 0 ? eqAlloc / totalAlloc : 0;
  const monthlyIncomePct = totalAlloc > 0 ? (annualIncome / totalAlloc * 100) / 12 : 0;

  // Rating bucket allocations
  const ratingBuckets = useMemo(() => {
    const b = { IG_HIGH: 0, IG_LOW: 0, HY_BB: 0, HY_B: 0, HY_CCC: 0 };
    bonds.forEach(bond => { b[getRatingBucket(bond.rating_num)] += bond.allocation || 0; });
    return b;
  }, [bonds]);
  const igPct = bondAlloc > 0 ? ((ratingBuckets.IG_HIGH + ratingBuckets.IG_LOW) / bondAlloc * 100) : 0;

  // Most illiquid bonds (for liquidity stress display)
  const illiquidBonds = useMemo(() =>
    [...bonds].filter(b => b.bid_ask_spread != null && b.bid_ask_spread > 0)
      .sort((a, b) => (b.bid_ask_spread || 0) - (a.bid_ask_spread || 0))
      .slice(0, 5),
  [bonds]);

  // ─── Enhanced calcScenario ──────────────────────────────────
  const calcScenario = ({ rateChg = 0, spreadChg = 0, defaultMultiplier = 0, fxChg = 0, eqChg = 0, liquidityMult = 0 }) => {
    if (totalAlloc === 0) return { priceChg: 0, income: 0, totalGross: 0, totalNet: 0, recoveryMonths: 0, autoSpreadChg: 0 };

    // Equity-bond correlation stress: auto-add spread widening for severe equity drawdowns
    let autoSpreadChg = 0;
    if (eqChg <= -30) autoSpreadChg = 100;
    else if (eqChg <= -20) autoSpreadChg = 50;
    const effectiveSpreadChg = spreadChg + autoSpreadChg;

    // Per-bond rate impact (with convexity for large moves)
    let rateImpactWeighted = 0;
    let spreadImpactWeighted = 0;
    let defaultLossWeighted = 0;
    let liquidationCost = 0;

    bonds.forEach(b => {
      const dur = b.duration || 0;
      const alloc = b.allocation || 0;
      if (alloc <= 0) return;
      const weight = alloc / totalAlloc;

      // Rate impact: convexity adjustment for moves > 100bp
      const dy = rateChg / 10000;
      let bondRateChg;
      if (Math.abs(rateChg) > 100) {
        const cvx = dur * dur * 0.5; // estimated convexity
        bondRateChg = (-dur * dy + 0.5 * cvx * dy * dy) * 100;
      } else {
        bondRateChg = -dur * dy * 100;
      }
      rateImpactWeighted += bondRateChg * weight;

      // Spread impact: dampening for large moves
      const ds = effectiveSpreadChg / 10000;
      let bondSpreadChg = -dur * ds * 100;
      if (effectiveSpreadChg >= 300) bondSpreadChg *= 0.90;
      else if (effectiveSpreadChg >= 200) bondSpreadChg *= 0.95;
      spreadImpactWeighted += bondSpreadChg * weight;

      // Default loss: rating-sensitive
      if (defaultMultiplier > 0) {
        const bucket = getRatingBucket(b.rating_num);
        const [baseRate, recoveryRate] = RATING_DEFAULTS[bucket];
        const loss = baseRate * defaultMultiplier * (1 - recoveryRate) * 100;
        defaultLossWeighted += loss * weight;
      }

      // Liquidity stress
      if (liquidityMult > 0) {
        const ba = b.bid_ask_spread || 0;
        liquidationCost += (ba * liquidityMult / 100) * weight;
      }
    });

    const bondPriceChg = rateImpactWeighted + spreadImpactWeighted - defaultLossWeighted - liquidationCost;
    const fxImpact = -fxChg * usdPct;
    const eqImpact = eqChg * wBeta * eqPct;
    const totalPriceChg = bondPriceChg + eqImpact + fxImpact;
    const income = annualIncome;
    const totalGross = totalPriceChg + baseReturn;
    const totalNet = totalGross - annualFees - formationFee;

    // Recovery time: months of coupon income to recover the price loss
    const recoveryMonths = (totalPriceChg < 0 && monthlyIncomePct > 0)
      ? Math.abs(totalPriceChg) / monthlyIncomePct : 0;

    return { priceChg: totalPriceChg, income, totalGross, totalNet, recoveryMonths, autoSpreadChg };
  };

  // ─── Scenario definitions ──────────────────────────────────
  const scenarios = [
    { category: 'RATE SCENARIOS', items: [
      { name: 'Rates unchanged', params: {} },
      { name: 'Rates +50bp', params: { rateChg: 50 } },
      { name: 'Rates +100bp', params: { rateChg: 100 } },
      { name: 'Rates +150bp (convexity adj.)', params: { rateChg: 150 } },
      { name: 'Rates -50bp', params: { rateChg: -50 } },
      { name: 'Rates -100bp', params: { rateChg: -100 } },
    ]},
    { category: 'SPREAD SCENARIOS', items: [
      { name: 'Spreads unchanged', params: {} },
      { name: 'OAS +50bp', params: { spreadChg: 50 } },
      { name: 'OAS +100bp', params: { spreadChg: 100 } },
      { name: 'OAS +200bp (dampened)', params: { spreadChg: 200 } },
      { name: 'OAS -50bp', params: { spreadChg: -50 } },
      { name: 'OAS -100bp', params: { spreadChg: -100 } },
    ]},
    { category: 'DEFAULT SCENARIOS', items: [
      { name: 'No defaults', params: {} },
      { name: 'Base case (1× rating defaults)', params: { defaultMultiplier: 1 } },
      { name: 'Mild recession (1.5× defaults)', params: { defaultMultiplier: 1.5 } },
      { name: 'Severe recession (3× defaults)', params: { defaultMultiplier: 3 } },
    ]},
    { category: 'FX SCENARIOS', items: [
      { name: 'EUR/USD unchanged', params: {} },
      { name: 'EUR/USD +5%', params: { fxChg: 5 } },
      { name: 'EUR/USD +10%', params: { fxChg: 10 } },
      { name: 'EUR/USD -5%', params: { fxChg: -5 } },
      { name: 'EUR/USD -10%', params: { fxChg: -10 } },
    ]},
    ...(equities.length > 0 ? [{ category: 'EQUITY SCENARIOS', items: [
      { name: 'Market unchanged', params: {} },
      { name: 'Market -10%', params: { eqChg: -10 } },
      { name: 'Market -20% (+50bp spread stress)', params: { eqChg: -20 } },
      { name: 'Market -30% (+100bp spread stress)', params: { eqChg: -30 } },
    ]}] : []),
    { category: 'LIQUIDITY STRESS', items: [
      { name: 'Normal conditions', params: {} },
      { name: 'Mild stress (3× bid-ask)', params: { liquidityMult: 3 } },
      { name: 'Severe stress (5× bid-ask)', params: { liquidityMult: 5 } },
    ]},
    { category: 'COMBINED STRESS', items: [
      { name: 'Mild recession', params: { rateChg: -50, spreadChg: 100, defaultMultiplier: 1.5, eqChg: -15, fxChg: 5 } },
      { name: 'Severe recession', params: { rateChg: -100, spreadChg: 200, defaultMultiplier: 3, eqChg: -30, fxChg: 10 } },
      { name: 'Inflation shock', params: { rateChg: 150, spreadChg: 50, eqChg: -10, fxChg: -5 } },
      { name: 'Soft landing', params: { rateChg: -50, spreadChg: -50, eqChg: 10 } },
    ]},
  ];

  // Chart data: flatten all scenarios (skip unchanged/empty)
  const chartData = useMemo(() => {
    const data = [];
    scenarios.forEach(group => {
      group.items.forEach(s => {
        if (Object.keys(s.params).length === 0) return;
        const r = calcScenario(s.params);
        data.push({ name: s.name.replace(/ \(.*\)/, ''), netReturn: parseFloat(r.totalNet.toFixed(2)), category: group.category });
      });
    });
    return data;
  }, [portfolio, clientSettings]);

  if (portfolio.length === 0) {
    return <div style={{ fontFamily: FONT, color: COLORS.textMuted, padding: 40, textAlign: 'center' }}>
      Add positions to the portfolio first to run scenario analysis.
    </div>;
  }

  const getExample = (cat) => {
    const m = METHODOLOGY[cat];
    if (!m?.example) return '';
    if (cat === 'RATE SCENARIOS' || cat === 'SPREAD SCENARIOS') return m.example(wDur);
    if (cat === 'FX SCENARIOS') return m.example(usdPct);
    if (cat === 'EQUITY SCENARIOS') return m.example(wBeta, eqPct);
    return m.example();
  };

  const TABLE_HEADERS = [
    { label: 'SCENARIO', width: '26%', align: 'left' },
    { label: 'PRICE CHG %', width: '13%', align: 'right' },
    { label: 'INCOME €', width: '13%', align: 'right' },
    { label: 'GROSS %', width: '14%', align: 'right' },
    { label: 'NET %', width: '14%', align: 'right' },
    { label: 'RECOVERY', width: '10%', align: 'right' },
  ];

  const recoveryColor = (mo) => {
    if (mo <= 0) return COLORS.textMuted;
    if (mo < 6) return COLORS.green;
    if (mo < 12) return COLORS.amber;
    return COLORS.red;
  };

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, color: COLORS.amber, letterSpacing: 2, margin: 0 }}>SCENARIO ANALYSIS</h2>
        <button onClick={() => setShowInfo('COLUMNS')}
          style={{ padding: '3px 10px', background: 'none', color: COLORS.cyan,
            border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 11, cursor: 'pointer' }}>
          ℹ Column Definitions
        </button>
      </div>
      <div style={{ fontSize: 10, color: COLORS.textMuted, marginBottom: 12 }}>
        Base return: {baseReturn.toFixed(2)}% | Duration: {wDur.toFixed(1)} | OAS: {wOas.toFixed(0)}bp |
        IG: {igPct.toFixed(0)}% HY: {(100 - igPct).toFixed(0)}% |
        Annual fees: {annualFees.toFixed(1)}% | Formation: {formationFee.toFixed(1)}% |
        USD: {(usdPct * 100).toFixed(0)}%{eqPct > 0 ? ` | Equity: ${(eqPct * 100).toFixed(0)}% (β${wBeta.toFixed(2)})` : ''}
      </div>

      {scenarios.map(group => (
        <div key={group.category} style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: COLORS.amber, letterSpacing: 1 }}>{group.category}</span>
            <button onClick={() => setShowInfo(group.category)}
              style={{ padding: '1px 6px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}33`, fontFamily: FONT, fontSize: 10,
                cursor: 'pointer', borderRadius: 0, lineHeight: '14px' }}>
              ℹ
            </button>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: FONT, tableLayout: 'fixed' }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                {TABLE_HEADERS.map(h => (
                  <th key={h.label} style={{ padding: '4px 8px', color: COLORS.textMuted, fontSize: 9,
                    textAlign: h.align, fontWeight: 'normal', width: h.width }}>{h.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {group.items.map(scenario => {
                const r = calcScenario(scenario.params);
                const meetsTarget = r.totalNet >= targetNet;
                return (
                  <tr key={scenario.name} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                    <td style={{ padding: '4px 8px', color: COLORS.white, fontSize: 10 }}>
                      {scenario.name}
                      {r.autoSpreadChg > 0 && !scenario.name.includes('spread stress') && (
                        <span style={{ color: COLORS.amber, fontSize: 8, marginLeft: 4 }}>+{r.autoSpreadChg}bp corr.</span>
                      )}
                    </td>
                    <td style={{ padding: '4px 8px', textAlign: 'right',
                      color: r.priceChg >= 0 ? COLORS.green : COLORS.red }}>
                      {r.priceChg >= 0 ? '+' : ''}{r.priceChg.toFixed(2)}%
                    </td>
                    <td style={{ padding: '4px 8px', textAlign: 'right', color: COLORS.textSecondary }}>
                      €{r.income.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </td>
                    <td style={{ padding: '4px 8px', textAlign: 'right', color: COLORS.textSecondary }}>
                      {r.totalGross >= 0 ? '+' : ''}{r.totalGross.toFixed(2)}%
                    </td>
                    <td style={{ padding: '4px 8px', textAlign: 'right', fontWeight: 'bold',
                      color: meetsTarget ? COLORS.green : COLORS.red }}>
                      {r.totalNet >= 0 ? '+' : ''}{r.totalNet.toFixed(2)}%
                    </td>
                    <td style={{ padding: '4px 8px', textAlign: 'right', fontSize: 10,
                      color: recoveryColor(r.recoveryMonths) }}>
                      {r.recoveryMonths > 0 ? r.recoveryMonths.toFixed(1) + 'mo' : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Illiquid positions sub-table after liquidity stress */}
          {group.category === 'LIQUIDITY STRESS' && illiquidBonds.length > 0 && (
            <div style={{ marginTop: 6, padding: '8px 10px', background: COLORS.card, border: `1px solid ${COLORS.cardBorder}` }}>
              <div style={{ fontSize: 9, color: COLORS.amber, marginBottom: 4, letterSpacing: 1 }}>MOST ILLIQUID POSITIONS</div>
              {illiquidBonds.map(b => (
                <div key={b.id} style={{ display: 'flex', gap: 8, fontSize: 10, padding: '2px 0', color: COLORS.textSecondary }}>
                  <span style={{ flex: 1, color: COLORS.white, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {b.issuer_name || b.isin}
                  </span>
                  <span style={{ width: 50, color: COLORS.red }}>B/A: {(b.bid_ask_spread || 0).toFixed(2)}</span>
                  <span style={{ width: 30 }}>{b.rating || '—'}</span>
                  <span style={{ width: 55, textAlign: 'right' }}>
                    {totalAlloc > 0 ? ((b.allocation || 0) / totalAlloc * 100).toFixed(1) + '%' : '—'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      {/* ─── Scenario Comparison Chart ──────────────────────── */}
      {chartData.length > 0 && (
        <div style={{ marginTop: 8, marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: COLORS.amber, letterSpacing: 1, marginBottom: 8 }}>SCENARIO COMPARISON</div>
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: '16px 8px 0 0' }}>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 80 }}>
                <XAxis dataKey="name" angle={-40} textAnchor="end" interval={0}
                  tick={{ fontSize: 8, fill: COLORS.textMuted }} height={80} />
                <YAxis tick={{ fontSize: 9, fill: COLORS.textMuted }}
                  tickFormatter={v => v + '%'} />
                <ReferenceLine y={targetNet} stroke={COLORS.cyan} strokeDasharray="3 3"
                  label={{ value: `Target ${targetNet}%`, fill: COLORS.cyan, fontSize: 9, position: 'insideTopRight' }} />
                <ReferenceLine y={0} stroke={COLORS.cardBorder} />
                <Tooltip
                  formatter={(v) => [v.toFixed(2) + '%', 'Net Return']}
                  contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 11 }}
                  labelStyle={{ color: COLORS.amber, fontSize: 10 }}
                  itemStyle={{ color: COLORS.white }} />
                <Bar dataKey="netReturn" radius={[2, 2, 0, 0]}>
                  {chartData.map((entry, i) => (
                    <Cell key={i} fill={entry.netReturn >= targetNet ? COLORS.green : entry.netReturn >= 0 ? COLORS.amber : COLORS.red} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Methodology info modal */}
      {showInfo && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
          onClick={() => setShowInfo(null)}>
          <div style={{ background: '#111', border: `1px solid ${COLORS.cyan}44`, padding: 24, width: 560,
            fontFamily: FONT, maxHeight: '80vh', overflowY: 'auto' }}
            onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <h3 style={{ color: COLORS.amber, fontSize: 14, margin: 0 }}>
                {showInfo === 'COLUMNS' ? COLUMNS_INFO.title : METHODOLOGY[showInfo]?.title || showInfo}
              </h3>
              <button onClick={() => setShowInfo(null)} style={{
                background: 'none', border: 'none', color: COLORS.textMuted, fontSize: 18, cursor: 'pointer' }}>×</button>
            </div>

            {showInfo === 'COLUMNS' ? (
              <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                {COLUMNS_INFO.items.map(([col, desc]) => (
                  <div key={col} style={{ marginBottom: 10 }}>
                    <span style={{ color: COLORS.amber, fontWeight: 'bold' }}>{col}</span>
                    <div style={{ color: COLORS.textSecondary, marginTop: 2 }}>{desc}</div>
                  </div>
                ))}
              </div>
            ) : METHODOLOGY[showInfo] ? (
              <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                <div style={{ background: COLORS.bgDark, padding: 10, marginBottom: 12, color: COLORS.cyan, fontSize: 11, whiteSpace: 'pre-line' }}>
                  {METHODOLOGY[showInfo].formula}
                </div>
                {METHODOLOGY[showInfo].explanation.map((line, i) => (
                  <p key={i} style={{ color: line ? COLORS.textSecondary : 'transparent', margin: '4px 0', fontSize: 11 }}>
                    {line || ' '}
                  </p>
                ))}
                <div style={{ marginTop: 12, padding: 10, background: COLORS.bgDark, borderLeft: `3px solid ${COLORS.green}` }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 10, marginBottom: 4 }}>EXAMPLE (using your portfolio)</div>
                  <div style={{ color: COLORS.green, fontSize: 12 }}>{getExample(showInfo)}</div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
