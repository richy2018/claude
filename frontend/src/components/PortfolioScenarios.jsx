import React, { useMemo } from 'react';
import { COLORS, FONT } from '../utils/theme';

export default function PortfolioScenarios({ portfolio, clientSettings }) {
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

  // Weighted metrics
  const wavg = (items, field) => {
    let sw = 0, swv = 0;
    items.forEach(i => { const v = i[field], w = i.allocation || 0; if (v != null && w > 0) { sw += w; swv += w * v; } });
    return sw > 0 ? swv / sw : 0;
  };

  const wDur = wavg(bonds, 'duration');
  const wYtm = wavg(bonds, 'ytm');
  const wOas = wavg(bonds, 'oas_spread');
  const wCpn = wavg(bonds, 'coupon');
  const wBeta = wavg(equities, 'beta') || 1;
  const eqExpRet = wavg(equities, 'expected_return');
  const annualIncome = bonds.reduce((s, b) => s + (b.coupon || 0) / 100 * (b.allocation || 0), 0) +
    equities.reduce((s, e) => s + (e.dividend_yield || 0) / 100 * (e.allocation || 0), 0);

  const baseReturn = totalAlloc > 0 ? (bondAlloc / totalAlloc * wYtm + eqAlloc / totalAlloc * eqExpRet) : 0;

  // Scenario calculator
  const calcScenario = ({ rateChg = 0, spreadChg = 0, defaultRate = 0, recovery = 0.4, fxChg = 0, eqChg = 0 }) => {
    if (totalAlloc === 0) return { priceChg: 0, income: 0, totalGross: 0, totalNet: 0, annualized: 0 };

    // Bond price impact from rates
    const ratePriceImpact = -wDur * (rateChg / 100); // as % of bond value

    // Bond price impact from spreads
    const spreadPriceImpact = -wDur * (spreadChg / 10000); // OAS in bp → decimal

    // Default loss
    const defaultLoss = defaultRate * (1 - recovery);

    // Total bond price change %
    const bondPriceChg = (ratePriceImpact + spreadPriceImpact - defaultLoss) * 100;

    // FX impact on USD portion only
    const usdPct = totalAlloc > 0 ? usdBondAlloc / totalAlloc : 0;
    const fxImpact = -fxChg * usdPct; // EUR strengthening = negative for USD holder

    // Equity impact
    const eqPct = totalAlloc > 0 ? eqAlloc / totalAlloc : 0;
    const eqImpact = eqChg * wBeta * eqPct;

    // Bond portion impact
    const bondPct = totalAlloc > 0 ? bondAlloc / totalAlloc : 0;
    const totalPriceChg = bondPriceChg * bondPct + eqImpact + fxImpact;

    const income = annualIncome;
    const totalGross = totalPriceChg + baseReturn;
    const totalNet = totalGross - annualFees - formationFee;

    return {
      priceChg: totalPriceChg,
      income,
      totalGross,
      totalNet,
      annualized: totalNet,
    };
  };

  // Define all scenarios
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

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white }}>
      <h2 style={{ fontSize: 18, color: COLORS.amber, letterSpacing: 2, marginBottom: 12 }}>SCENARIO ANALYSIS</h2>
      <div style={{ fontSize: 10, color: COLORS.textMuted, marginBottom: 12 }}>
        Base return: {baseReturn.toFixed(2)}% | Duration: {wDur.toFixed(1)} | OAS: {wOas.toFixed(0)}bp |
        Annual fees: {annualFees.toFixed(1)}% | Formation: {formationFee.toFixed(1)}% |
        USD exposure: {totalAlloc > 0 ? (usdBondAlloc / totalAlloc * 100).toFixed(0) : 0}%
      </div>

      {scenarios.map(group => (
        <div key={group.category} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 4, letterSpacing: 1 }}>{group.category}</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: FONT }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                {['SCENARIO', 'PRICE CHG %', 'INCOME €', 'GROSS RETURN %', 'NET RETURN %'].map(h => (
                  <th key={h} style={{ padding: '4px 8px', color: COLORS.textMuted, fontSize: 9,
                    textAlign: h === 'SCENARIO' ? 'left' : 'right', fontWeight: 'normal' }}>{h}</th>
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
    </div>
  );
}
