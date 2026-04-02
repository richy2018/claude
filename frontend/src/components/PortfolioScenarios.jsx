import React, { useState, useMemo } from 'react';
import { COLORS, FONT } from '../utils/theme';

const METHODOLOGY = {
  'RATE SCENARIOS': {
    title: 'Rate Scenario Methodology',
    formula: 'Price Change % = -Duration × ΔYield(decimal) × 100',
    explanation: [
      'Models the impact of parallel interest rate shifts on bond prices using modified duration as a linear approximation.',
      'ΔYield is converted from basis points to decimal: 50bp ÷ 10,000 = 0.005',
      'Duration measures price sensitivity — a duration of 3 means a 1% rate rise causes ~3% price decline.',
      'Applied only to the bond portion of the portfolio, weighted by bond allocation %.',
      'Assumes a parallel shift across the entire yield curve (all maturities move equally).',
      'Limitation: duration is a linear approximation. For large rate moves (>100bp), convexity effects make actual price changes slightly different.',
    ],
    example: (dur) => `Duration ${dur.toFixed(1)}, Rates +50bp → -${dur.toFixed(1)} × 0.005 × 100 = ${(-dur * 0.005 * 100).toFixed(2)}%`,
  },
  'SPREAD SCENARIOS': {
    title: 'Spread Scenario Methodology',
    formula: 'Price Change % = -Duration × ΔSpread(decimal) × 100',
    explanation: [
      'Models credit spread widening/tightening impact on bond prices.',
      'Uses the same duration sensitivity as rate scenarios — OAS spread changes affect bond prices identically to rate changes.',
      'Spread widening (positive ΔSpread) = bond prices fall (credit risk repricing).',
      'Spread tightening (negative ΔSpread) = bond prices rise (improving credit conditions).',
      'This is independent of risk-free rate changes — spread scenarios isolate credit risk.',
      'In practice, spreads and rates can move together (e.g., recession: rates fall + spreads widen).',
    ],
    example: (dur) => `Duration ${dur.toFixed(1)}, OAS +100bp → -${dur.toFixed(1)} × 0.01 × 100 = ${(-dur * 0.01 * 100).toFixed(2)}%`,
  },
  'DEFAULT SCENARIOS': {
    title: 'Default Scenario Methodology',
    formula: 'Loss % = Default Rate × (1 - Recovery Rate) × 100',
    explanation: [
      'Models expected loss from bond defaults across the portfolio.',
      'Default Rate = assumed percentage of bonds (by face value) that default over the period.',
      'Recovery Rate = percentage of face value recovered after default (typically 30-40% for senior unsecured).',
      'Loss Given Default (LGD) = 1 - Recovery Rate.',
      'Applied proportionally across all bonds — does not target specific issuers.',
      'Example: 2% default rate × 60% LGD = 1.20% portfolio loss.',
      'In practice, defaults cluster in lower-rated credits. HY portfolios face higher default risk than IG.',
    ],
    example: () => '2% default, 40% recovery → 0.02 × (1 - 0.40) × 100 = 1.20% loss',
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
    formula: 'Equity Impact % = Market Change % × Portfolio Beta × Equity Allocation %',
    explanation: [
      'Models equity market drawdown impact on the equity portion of the portfolio.',
      'Uses the weighted average portfolio beta to estimate sensitivity to market moves.',
      'Beta = 1.0 means the equity moves in line with the market. Beta > 1 = more volatile, < 1 = less volatile.',
      'Applied only to the equity allocation — bonds are assumed uncorrelated with equity markets in this model.',
      'In practice, during severe stress, correlations increase and bonds can also be affected (flight to quality).',
    ],
    example: (beta, eqPct) => `Market -20%, Beta ${beta.toFixed(2)}, Equity allocation ${(eqPct * 100).toFixed(0)}% → -20% × ${beta.toFixed(2)} × ${(eqPct * 100).toFixed(0)}% = ${(-20 * beta * eqPct).toFixed(2)}%`,
  },
  'COMBINED STRESS': {
    title: 'Combined Stress Scenario Methodology',
    formula: 'Total Impact = Rate Impact + Spread Impact + Default Loss + FX Impact + Equity Impact',
    explanation: [
      'Applies multiple shocks simultaneously to model realistic macro scenarios:',
      '',
      'Mild recession: Rates -50bp (central bank easing), Spreads +100bp (credit stress), Equities -15%, EUR/USD +5% (USD weakens in risk-off)',
      'Severe recession: Rates -100bp, Spreads +200bp, 2% defaults (40% recovery), Equities -30%, EUR/USD +10%',
      'Inflation shock: Rates +150bp (central bank tightening), Spreads +50bp (uncertainty), Equities -10%, EUR/USD -5% (USD strengthens on higher rates)',
      'Soft landing: Rates -50bp (gradual easing), Spreads -50bp (improving credit), Equities +10%',
      '',
      'Total impact is the sum of all individual shocks (no diversification benefit / correlation adjustment).',
      'This is a simplification — in reality, shocks interact (e.g., rate cuts partially offset spread widening).',
    ],
    example: () => 'Severe recession: rate impact + spread impact + default loss + FX impact + equity impact = total',
  },
};

const COLUMNS_INFO = {
  title: 'Column Definitions',
  items: [
    ['PRICE CHG %', 'Change in portfolio market value from the scenario shock. Negative = portfolio loses value.'],
    ['INCOME €', 'Annual coupon income (bonds) + dividend income (equities). Constant across scenarios — assumes no defaults affect coupon payments.'],
    ['GROSS RETURN %', 'Price Change + Base Expected Return (weighted YTM for bonds + expected return for equities). Before fees.'],
    ['NET RETURN %', 'Gross Return - Annual Fees (management + custody) - Formation Fee. This is the investor\'s actual return. Green = meets target, Red = below target.'],
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

  const calcScenario = ({ rateChg = 0, spreadChg = 0, defaultRate = 0, recovery = 0.4, fxChg = 0, eqChg = 0 }) => {
    if (totalAlloc === 0) return { priceChg: 0, income: 0, totalGross: 0, totalNet: 0 };
    const ratePriceImpact = -wDur * (rateChg / 10000) * 100;
    const spreadPriceImpact = -wDur * (spreadChg / 10000) * 100;
    const defaultLoss = defaultRate * (1 - recovery) * 100;
    const bondPriceChg = ratePriceImpact + spreadPriceImpact - defaultLoss;
    const fxImpact = -fxChg * usdPct;
    const eqImpact = eqChg * wBeta * eqPct;
    const bondPct = totalAlloc > 0 ? bondAlloc / totalAlloc : 0;
    const totalPriceChg = bondPriceChg * bondPct + eqImpact + fxImpact;
    const income = annualIncome;
    const totalGross = totalPriceChg + baseReturn;
    const totalNet = totalGross - annualFees - formationFee;
    return { priceChg: totalPriceChg, income, totalGross, totalNet };
  };

  const scenarios = [
    { category: 'RATE SCENARIOS', items: [
      { name: 'Rates unchanged', params: {} },
      { name: 'Rates +50bp', params: { rateChg: 50 } },
      { name: 'Rates +100bp', params: { rateChg: 100 } },
      { name: 'Rates +150bp', params: { rateChg: 150 } },
      { name: 'Rates -50bp', params: { rateChg: -50 } },
      { name: 'Rates -100bp', params: { rateChg: -100 } },
    ]},
    { category: 'SPREAD SCENARIOS', items: [
      { name: 'Spreads unchanged', params: {} },
      { name: 'OAS +50bp', params: { spreadChg: 50 } },
      { name: 'OAS +100bp', params: { spreadChg: 100 } },
      { name: 'OAS +200bp', params: { spreadChg: 200 } },
      { name: 'OAS -50bp', params: { spreadChg: -50 } },
      { name: 'OAS -100bp', params: { spreadChg: -100 } },
    ]},
    { category: 'DEFAULT SCENARIOS', items: [
      { name: 'No defaults', params: {} },
      { name: '1% default, 40% recovery', params: { defaultRate: 0.01, recovery: 0.4 } },
      { name: '2% default, 40% recovery', params: { defaultRate: 0.02, recovery: 0.4 } },
      { name: '5% default, 30% recovery', params: { defaultRate: 0.05, recovery: 0.3 } },
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
      { name: 'Market -20%', params: { eqChg: -20 } },
      { name: 'Market -30%', params: { eqChg: -30 } },
    ]}] : []),
    { category: 'COMBINED STRESS', items: [
      { name: 'Mild recession', params: { rateChg: -50, spreadChg: 100, eqChg: -15, fxChg: 5 } },
      { name: 'Severe recession', params: { rateChg: -100, spreadChg: 200, defaultRate: 0.02, recovery: 0.4, eqChg: -30, fxChg: 10 } },
      { name: 'Inflation shock', params: { rateChg: 150, spreadChg: 50, eqChg: -10, fxChg: -5 } },
      { name: 'Soft landing', params: { rateChg: -50, spreadChg: -50, eqChg: 10 } },
    ]},
  ];

  if (portfolio.length === 0) {
    return <div style={{ fontFamily: FONT, color: COLORS.textMuted, padding: 40, textAlign: 'center' }}>
      Add positions to the portfolio first to run scenario analysis.
    </div>;
  }

  // Get example for current methodology
  const getExample = (cat) => {
    const m = METHODOLOGY[cat];
    if (!m?.example) return '';
    if (cat === 'RATE SCENARIOS' || cat === 'SPREAD SCENARIOS') return m.example(wDur);
    if (cat === 'FX SCENARIOS') return m.example(usdPct);
    if (cat === 'EQUITY SCENARIOS') return m.example(wBeta, eqPct);
    return m.example();
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
        Annual fees: {annualFees.toFixed(1)}% | Formation: {formationFee.toFixed(1)}% |
        USD exposure: {(usdPct * 100).toFixed(0)}%
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
                {[
                  { label: 'SCENARIO', width: '30%', align: 'left' },
                  { label: 'PRICE CHG %', width: '15%', align: 'right' },
                  { label: 'INCOME €', width: '15%', align: 'right' },
                  { label: 'GROSS RETURN %', width: '20%', align: 'right' },
                  { label: 'NET RETURN %', width: '20%', align: 'right' },
                ].map(h => (
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
                    <td style={{ padding: '4px 8px', color: COLORS.white }}>{scenario.name}</td>
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
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}

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
                <div style={{ background: COLORS.bgDark, padding: 10, marginBottom: 12, color: COLORS.cyan, fontSize: 11 }}>
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
