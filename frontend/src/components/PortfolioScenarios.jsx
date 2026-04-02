import React, { useState, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, ReferenceLine, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import { COLORS, FONT } from '../utils/theme';

// Rating-specific annual default rates (Moody's/S&P historical calibration)
const RATING_DEFAULTS = {
  IG_HIGH: 0.0005,  // AAA/AA/A: 0.05% base default
  IG_LOW:  0.0020,  // BBB: 0.20% base default
  HY_BB:   0.0080,  // BB: 0.80% base default
  HY_B:    0.0300,  // B: 3.00% base default
  HY_CCC:  0.1500,  // CCC+: 15.00% base default
};

// Recovery rates by payment rank (seniority-based)
const RECOVERY_BY_RANK = {
  'Secured': 0.65, 'Sr Secured': 0.60, 'Sr Unsecured': 0.45, 'Subordinated': 0.25,
};
const DEFAULT_RECOVERY = 0.40;

// Treasury curve tenor points for interpolation
const TENOR_YEARS = { DGS1: 1, DGS2: 2, DGS5: 5, DGS10: 10, DGS30: 30 };

function interpolateTreasuryYield(curve, yearsToMaturity) {
  if (!curve) return null;
  const tenors = Object.entries(TENOR_YEARS)
    .map(([k, yr]) => ({ yr, val: curve[k] }))
    .filter(t => t.val != null)
    .sort((a, b) => a.yr - b.yr);
  if (tenors.length === 0) return null;
  const y = Math.max(tenors[0].yr, Math.min(tenors[tenors.length - 1].yr, yearsToMaturity || 5));
  // Exact match
  const exact = tenors.find(t => t.yr === y);
  if (exact) return exact.val;
  // Find surrounding points
  let lo = tenors[0], hi = tenors[tenors.length - 1];
  for (let i = 0; i < tenors.length - 1; i++) {
    if (tenors[i].yr <= y && tenors[i + 1].yr >= y) { lo = tenors[i]; hi = tenors[i + 1]; break; }
  }
  const frac = (y - lo.yr) / (hi.yr - lo.yr);
  return lo.val + frac * (hi.val - lo.val);
}

function calcCallProb(bond, treasuryCurve, medianGSpreadByRating, rateShockBp = 0) {
  if (!bond.maturity_type || !bond.maturity_type.includes('CALL')) return 0;
  const yrsToMat = bond.years_to_maturity || 5;
  const treasuryYield = interpolateTreasuryYield(treasuryCurve, yrsToMat);
  if (treasuryYield == null) return 0;
  const medianGSpread = (medianGSpreadByRating || {})[bond.rating] || 0;
  const marketYield = (treasuryYield + rateShockBp / 100) + medianGSpread / 100;
  const spread = (bond.coupon || 0) - marketYield;
  let prob;
  if (spread > 1.5) prob = 0.80;
  else if (spread > 0.5) prob = 0.50;
  else prob = 0.20;
  if (bond.price > 100) prob = Math.min(1.0, prob + 0.10);
  return prob;
}

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
    formula: 'Per-bond loss = Rating Default Rate × Multiplier × (1 - Recovery Rate by Seniority)',
    explanation: [
      'Uses rating-specific default rates calibrated to historical Moody\'s/S&P default studies:',
      '',
      '• AAA/AA/A: 0.05% base default rate',
      '• BBB: 0.20% base default rate',
      '• BB: 0.80% base default rate',
      '• B: 3.00% base default rate',
      '• CCC and below: 15.00% base default rate',
      '',
      'Recovery rates vary by payment rank (seniority):',
      '• Secured: 65% | Sr Secured: 60% | Sr Unsecured: 45% | Subordinated: 25% | Unknown: 40%',
      '',
      'Scenario multiplier scales the base rate: 1× (base), 1.5× (mild recession), 3× (severe recession).',
      'Defaulted bonds also lose their coupon income, reducing portfolio income in stress scenarios.',
    ],
    example: () => 'BBB Sr Unsecured bond, 1.5× multiplier: 0.20% × 1.5 × (1 - 45%) = 0.165% loss + coupon income loss',
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
    example: () => 'Bond with 0.40 bid-ask, severe stress: 0.40 × 5 = 2.00% liquidation cost for that position',
  },
  'COMBINED STRESS': {
    title: 'Combined Stress Scenario Methodology',
    formula: 'Total = Rate + Spread + Defaults + FX + Equity + Correlation Stress\nRate-decline scenarios use YTW (callable bonds likely called)',
    explanation: [
      'Applies multiple shocks simultaneously to model realistic macro scenarios:',
      '',
      'Mild recession: Rates -50bp, Spreads +100bp, Defaults (1.5×), Equities -15%, EUR/USD +5%',
      'Severe recession: Rates -100bp, Spreads +200bp, Defaults (3×), Equities -30%, USD strengthens -7%',
      'Inflation shock: Rates +150bp (with convexity), Spreads +50bp, Equities -10%, EUR/USD -5%',
      'Soft landing: Rates -50bp, Spreads -50bp, Equities +10%',
      'Stagflation: Rates +100bp, Spreads +150bp, Defaults (2×), Equities -20%, EUR/USD +5%',
      'Tariff / Trade war: Rates +50bp, Spreads +75bp, Defaults (1.5×), Equities -15%, EUR/USD +3%',
      'Credit crisis: Rates -75bp, Spreads +250bp, Defaults (3×), Equities -25%, USD strengthens -5%',
      '',
      'Click any combined stress row to expand per-bond impact breakdown.',
      'Rate-decline scenarios use YTW as the base return assumption (callable bonds get called).',
    ],
    example: () => 'Severe recession: rate (convexity-adjusted) + spread (dampened) + defaults (seniority-based recovery) + FX + equity + correlation stress',
  },
};

const COLUMNS_INFO = {
  title: 'Column Definitions',
  items: [
    ['PRICE CHG %', 'Change in portfolio market value from the scenario shock. Negative = portfolio loses value.'],
    ['INCOME €', 'Annual coupon income (bonds) + dividend income (equities). Adjusts for estimated defaults — defaulted bonds lose their coupon income.'],
    ['GROSS RETURN %', 'Price Change + Base Expected Return. Uses min(YTM, YTW) for base case; YTW for rate-decline scenarios (callable bonds likely called). Before fees.'],
    ['NET RETURN %', 'Gross Return - Annual Fees (management + custody) - Formation Fee. This is the investor\'s actual return. Green = meets target, Red = below target.'],
    ['RECOVERY (mo)', 'Months to recover the price loss from coupon/dividend income alone. |Price Loss| ÷ (Monthly Income as % of portfolio). Green < 6 months, Amber 6-12 months, Red > 12 months. Dash for gains.'],
  ],
};

export default function PortfolioScenarios({ portfolio, clientSettings, bondUniverse, treasuryCurve }) {
  const [showInfo, setShowInfo] = useState(null);
  const [customParams, setCustomParams] = useState({ rateChg: 0, spreadChg: 0, defaultMultiplier: 0, fxChg: 0, eqChg: 0, liquidityMult: 0 });
  const [customResult, setCustomResult] = useState(null);
  const [expandedScenario, setExpandedScenario] = useState(null);

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

  // Effective yield per bond: min(YTM, YTW) — accounts for call risk on callable bonds
  const wEffYield = (() => {
    let sw = 0, swv = 0;
    bonds.forEach(b => {
      const w = b.allocation || 0;
      if (w > 0 && b.ytm != null) {
        const ytw = b.ytw != null ? b.ytw : b.ytm;
        sw += w; swv += w * Math.min(b.ytm, ytw);
      }
    });
    return sw > 0 ? swv / sw : 0;
  })();
  const wYtw = (() => {
    let sw = 0, swv = 0;
    bonds.forEach(b => {
      const w = b.allocation || 0;
      const ytw = b.ytw != null ? b.ytw : b.ytm;
      if (w > 0 && ytw != null) { sw += w; swv += w * ytw; }
    });
    return sw > 0 ? swv / sw : 0;
  })();
  const baseReturn = totalAlloc > 0 ? (bondAlloc / totalAlloc * wEffYield + eqAlloc / totalAlloc * eqExpRet) : 0;
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

  // Median G-Spread by rating from full bond universe (for market yield estimation)
  const medianGSpreadByRating = useMemo(() => {
    const byRating = {};
    (bondUniverse || []).forEach(b => {
      if (b.rating && b.g_spread != null) {
        if (!byRating[b.rating]) byRating[b.rating] = [];
        byRating[b.rating].push(b.g_spread);
      }
    });
    return Object.fromEntries(Object.entries(byRating).map(([r, spreads]) => {
      spreads.sort((a, b) => a - b);
      return [r, spreads[Math.floor(spreads.length / 2)]];
    }));
  }, [bondUniverse]);

  // Call probability per bond (base case, no rate shock)
  const callProbByBond = useMemo(() => {
    const m = {};
    bonds.forEach(b => { m[b.id] = calcCallProb(b, treasuryCurve, medianGSpreadByRating, 0); });
    return m;
  }, [bonds, treasuryCurve, medianGSpreadByRating]);

  // YTW-based base return for rate-decline scenarios (callable bonds capped at YTW)
  const rateDeclineBaseReturn = totalAlloc > 0 ? (bondAlloc / totalAlloc * wYtw + eqAlloc / totalAlloc * eqExpRet) : 0;

  // ─── Enhanced calcScenario ──────────────────────────────────
  const calcScenario = ({ rateChg = 0, spreadChg = 0, defaultMultiplier = 0, fxChg = 0, eqChg = 0, liquidityMult = 0 }) => {
    // Rate-decline scenarios use YTW (callable bonds likely get called)
    const isRateDecline = rateChg < 0;
    const effectiveBaseReturn = isRateDecline ? rateDeclineBaseReturn : baseReturn;
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
    let defaultedIncomeLoss = 0;

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

      // Default loss: rating-sensitive with seniority-based recovery
      if (defaultMultiplier > 0) {
        const bucket = getRatingBucket(b.rating_num);
        const baseRate = RATING_DEFAULTS[bucket];
        const recoveryRate = RECOVERY_BY_RANK[b.payment_rank] ?? DEFAULT_RECOVERY;
        const loss = baseRate * defaultMultiplier * (1 - recoveryRate) * 100;
        defaultLossWeighted += loss * weight;
        // Defaulted bonds also lose their coupon income
        defaultedIncomeLoss += baseRate * defaultMultiplier * (b.coupon || 0) / 100 * alloc;
      }

      // Liquidity stress
      if (liquidityMult > 0) {
        const ba = b.bid_ask_spread || 0;
        liquidationCost += (ba * liquidityMult) * weight;
      }
    });

    const bondPriceChg = rateImpactWeighted + spreadImpactWeighted - defaultLossWeighted - liquidationCost;
    const fxImpact = -fxChg * usdPct;
    const eqImpact = eqChg * wBeta * eqPct;
    const totalPriceChg = bondPriceChg + eqImpact + fxImpact;
    const income = annualIncome - defaultedIncomeLoss;
    const totalGross = totalPriceChg + effectiveBaseReturn;
    const totalNet = totalGross - annualFees - formationFee;

    // Recovery time: months of coupon income to recover the price loss
    const recoveryMonths = (totalPriceChg < 0 && monthlyIncomePct > 0)
      ? Math.abs(totalPriceChg) / monthlyIncomePct : 0;

    return { priceChg: totalPriceChg, income, totalGross, totalNet, recoveryMonths, autoSpreadChg };
  };

  // Per-bond breakdown for drill-down
  const calcPerBond = ({ rateChg = 0, spreadChg = 0, defaultMultiplier = 0, fxChg = 0, liquidityMult = 0 }) => {
    let autoSpreadChg = 0;
    const effectiveSpreadChg = spreadChg + autoSpreadChg;
    return bonds.map(b => {
      const dur = b.duration || 0;
      const alloc = b.allocation || 0;
      if (alloc <= 0) return null;
      const dy = rateChg / 10000;
      let rateImpact;
      if (Math.abs(rateChg) > 100) {
        const cvx = dur * dur * 0.5;
        rateImpact = (-dur * dy + 0.5 * cvx * dy * dy) * 100;
      } else {
        rateImpact = -dur * dy * 100;
      }
      const ds = effectiveSpreadChg / 10000;
      let spreadImpact = -dur * ds * 100;
      if (effectiveSpreadChg >= 300) spreadImpact *= 0.90;
      else if (effectiveSpreadChg >= 200) spreadImpact *= 0.95;
      let defaultLoss = 0;
      if (defaultMultiplier > 0) {
        const bucket = getRatingBucket(b.rating_num);
        const baseRate = RATING_DEFAULTS[bucket];
        const recoveryRate = RECOVERY_BY_RANK[b.payment_rank] ?? DEFAULT_RECOVERY;
        defaultLoss = baseRate * defaultMultiplier * (1 - recoveryRate) * 100;
      }
      let liqCost = 0;
      if (liquidityMult > 0) { liqCost = (b.bid_ask_spread || 0) * liquidityMult; }
      const fxImpact = b.currency === 'USD' ? -fxChg : 0;
      const total = rateImpact + spreadImpact - defaultLoss - liqCost + fxImpact;
      const cp = calcCallProb(b, treasuryCurve, medianGSpreadByRating, rateChg);
      const recoveryMo = total < 0 && (b.coupon || 0) > 0 ? Math.abs(total) / ((b.coupon || 0) / 12) : 0;
      return {
        name: b.issuer_name || b.isin, rating: b.rating, dur: dur.toFixed(1),
        oas: (b.oas_spread || 0).toFixed(0), rateImpact, spreadImpact,
        defaultLoss, fxImpact, total, callProb: cp, recoveryMo,
      };
    }).filter(Boolean).sort((a, b) => a.total - b.total);
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
      { name: 'Severe recession', params: { rateChg: -100, spreadChg: 200, defaultMultiplier: 3, eqChg: -30, fxChg: -7 } },
      { name: 'Inflation shock', params: { rateChg: 150, spreadChg: 50, eqChg: -10, fxChg: -5 } },
      { name: 'Soft landing', params: { rateChg: -50, spreadChg: -50, eqChg: 10 } },
      { name: 'Stagflation', params: { rateChg: 100, spreadChg: 150, defaultMultiplier: 2.0, eqChg: -20, fxChg: 5 } },
      { name: 'Tariff / Trade war', params: { rateChg: 50, spreadChg: 75, defaultMultiplier: 1.5, eqChg: -15, fxChg: 3 } },
      { name: 'Credit crisis', params: { rateChg: -75, spreadChg: 250, defaultMultiplier: 3, eqChg: -25, fxChg: -5 } },
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
        Base return: {baseReturn.toFixed(2)}% | Wtd YTM: {wYtm.toFixed(2)}% | Wtd YTW: {wYtw.toFixed(2)}% | Duration: {wDur.toFixed(1)} | OAS: {wOas.toFixed(0)}bp |
        IG: {igPct.toFixed(0)}% HY: {(100 - igPct).toFixed(0)}% |
        Annual fees: {annualFees.toFixed(1)}% | Formation: {formationFee.toFixed(1)}% |
        USD: {(usdPct * 100).toFixed(0)}%{eqPct > 0 ? ` | Equity: ${(eqPct * 100).toFixed(0)}% (β${wBeta.toFixed(2)})` : ''}
      </div>
      <div style={{ fontSize: 9, color: COLORS.textMuted, marginBottom: 12, fontStyle: 'italic' }}>
        All returns shown are annualized (1-year horizon). Income adjusts for estimated defaults.
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
                const isCombined = group.category === 'COMBINED STRESS' && Object.keys(scenario.params).length > 0;
                const isExpanded = expandedScenario === scenario.name;
                return (
                  <React.Fragment key={scenario.name}>
                    <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                      cursor: isCombined ? 'pointer' : 'default' }}
                      onClick={() => isCombined && setExpandedScenario(isExpanded ? null : scenario.name)}>
                      <td style={{ padding: '4px 8px', color: COLORS.white, fontSize: 10 }}>
                        {isCombined && <span style={{ fontSize: 8, marginRight: 4, color: COLORS.cyan }}>{isExpanded ? '▼' : '▶'}</span>}
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
                    {isCombined && isExpanded && (
                      <tr>
                        <td colSpan={6} style={{ padding: '4px 8px 8px 20px', background: COLORS.bgDark }}>
                          <div style={{ fontSize: 8, color: COLORS.textMuted, marginBottom: 4, letterSpacing: 1 }}>
                            PER-BOND IMPACT — sorted worst first
                          </div>
                          <div style={{ display: 'flex', gap: 6, fontSize: 8, color: COLORS.textMuted, padding: '2px 0',
                            borderBottom: `1px solid ${COLORS.cardBorder}33` }}>
                            <span style={{ flex: 1 }}>BOND</span>
                            <span style={{ width: 30 }}>RTG</span>
                            <span style={{ width: 30 }}>DUR</span>
                            <span style={{ width: 35 }}>OAS</span>
                            <span style={{ width: 45, textAlign: 'right' }}>RATE %</span>
                            <span style={{ width: 45, textAlign: 'right' }}>SPREAD %</span>
                            <span style={{ width: 45, textAlign: 'right' }}>DFLT %</span>
                            <span style={{ width: 35, textAlign: 'right' }}>FX %</span>
                            <span style={{ width: 50, textAlign: 'right' }}>TOTAL %</span>
                            <span style={{ width: 40, textAlign: 'right' }}>RCVRY</span>
                          </div>
                          {calcPerBond(scenario.params).map((pb, i) => (
                            <div key={i} style={{ display: 'flex', gap: 6, fontSize: 9, padding: '2px 0',
                              color: COLORS.textSecondary, borderBottom: `1px solid ${COLORS.cardBorder}11` }}>
                              <span style={{ flex: 1, color: COLORS.white, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {pb.name}
                              </span>
                              <span style={{ width: 30 }}>{pb.rating || '—'}</span>
                              <span style={{ width: 30 }}>{pb.dur}</span>
                              <span style={{ width: 35 }}>{pb.oas}bp</span>
                              <span style={{ width: 45, textAlign: 'right', color: pb.rateImpact >= 0 ? COLORS.green : COLORS.red }}>
                                {pb.rateImpact >= 0 ? '+' : ''}{pb.rateImpact.toFixed(2)}
                              </span>
                              <span style={{ width: 45, textAlign: 'right', color: pb.spreadImpact >= 0 ? COLORS.green : COLORS.red }}>
                                {pb.spreadImpact >= 0 ? '+' : ''}{pb.spreadImpact.toFixed(2)}
                              </span>
                              <span style={{ width: 45, textAlign: 'right', color: COLORS.red }}>
                                {pb.defaultLoss > 0 ? '-' + pb.defaultLoss.toFixed(3) : '—'}
                              </span>
                              <span style={{ width: 35, textAlign: 'right', color: pb.fxImpact >= 0 ? COLORS.green : COLORS.red }}>
                                {pb.fxImpact !== 0 ? (pb.fxImpact >= 0 ? '+' : '') + pb.fxImpact.toFixed(1) : '—'}
                              </span>
                              <span style={{ width: 50, textAlign: 'right', fontWeight: 'bold',
                                color: pb.total >= 0 ? COLORS.green : COLORS.red }}>
                                {pb.total >= 0 ? '+' : ''}{pb.total.toFixed(2)}%
                              </span>
                              <span style={{ width: 40, textAlign: 'right', fontSize: 8,
                                color: recoveryColor(pb.recoveryMo) }}>
                                {pb.recoveryMo > 0 ? pb.recoveryMo.toFixed(1) + 'mo' : '—'}
                              </span>
                            </div>
                          ))}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
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

          {/* Callable bond call probability after rate scenarios */}
          {group.category === 'RATE SCENARIOS' && bonds.some(b => (callProbByBond[b.id] || 0) > 0) && (
            <div style={{ marginTop: 6, padding: '8px 10px', background: COLORS.card, border: `1px solid ${COLORS.cardBorder}` }}>
              <div style={{ fontSize: 9, color: COLORS.amber, marginBottom: 4, letterSpacing: 1 }}>CALLABLE BOND CALL PROBABILITY</div>
              <div style={{ display: 'flex', gap: 8, fontSize: 8, padding: '2px 0', color: COLORS.textMuted, borderBottom: `1px solid ${COLORS.cardBorder}33` }}>
                <span style={{ flex: 1 }}>BOND</span>
                <span style={{ width: 35 }}>RTG</span>
                <span style={{ width: 40 }}>CPN</span>
                <span style={{ width: 40 }}>YTM</span>
                <span style={{ width: 40 }}>YTW</span>
                <span style={{ width: 50 }}>MKT YLD</span>
                <span style={{ width: 55, textAlign: 'right' }}>CALL PROB</span>
              </div>
              {bonds.filter(b => (callProbByBond[b.id] || 0) > 0).map(b => {
                const cp = callProbByBond[b.id] || 0;
                const yrsToMat = b.years_to_maturity || 5;
                const tsy = interpolateTreasuryYield(treasuryCurve, yrsToMat);
                const gSprd = (medianGSpreadByRating[b.rating] || 0) / 100;
                const mktYld = tsy != null ? tsy + gSprd : null;
                return (
                  <div key={b.id} style={{ display: 'flex', gap: 8, fontSize: 10, padding: '2px 0', color: COLORS.textSecondary }}>
                    <span style={{ flex: 1, color: COLORS.white, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {b.issuer_name || b.isin}
                    </span>
                    <span style={{ width: 35 }}>{b.rating || '—'}</span>
                    <span style={{ width: 40 }}>{(b.coupon || 0).toFixed(2)}</span>
                    <span style={{ width: 40 }}>{(b.ytm || 0).toFixed(2)}</span>
                    <span style={{ width: 40 }}>{b.ytw != null ? b.ytw.toFixed(2) : '—'}</span>
                    <span style={{ width: 50 }}>{mktYld != null ? mktYld.toFixed(2) + '%' : '—'}</span>
                    <span style={{ width: 55, textAlign: 'right', fontWeight: 'bold',
                      color: cp >= 0.6 ? COLORS.red : cp >= 0.3 ? COLORS.amber : COLORS.textMuted }}>
                      {(cp * 100).toFixed(0)}%
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ))}

      {/* ─── Custom Scenario Builder ──────────────────────── */}
      <div style={{ marginBottom: 16, padding: '12px 10px', background: COLORS.card, border: `1px solid ${COLORS.cardBorder}` }}>
        <div style={{ fontSize: 11, color: COLORS.amber, letterSpacing: 1, marginBottom: 8 }}>CUSTOM SCENARIO BUILDER</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          {[
            { key: 'rateChg', label: 'Rate Chg (bp)', step: 25 },
            { key: 'spreadChg', label: 'Spread Chg (bp)', step: 25 },
            { key: 'defaultMultiplier', label: 'Default ×', step: 0.5 },
            { key: 'fxChg', label: 'EUR/USD Chg %', step: 1 },
            { key: 'eqChg', label: 'Equity Chg %', step: 5 },
            { key: 'liquidityMult', label: 'Liquidity ×', step: 1 },
          ].map(f => (
            <div key={f.key} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <label style={{ fontSize: 8, color: COLORS.textMuted, letterSpacing: 0.5 }}>{f.label}</label>
              <input type="number" step={f.step}
                value={customParams[f.key]}
                onChange={e => setCustomParams(p => ({ ...p, [f.key]: parseFloat(e.target.value) || 0 }))}
                style={{ width: 80, padding: '4px 6px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`,
                  color: COLORS.white, fontFamily: FONT, fontSize: 11, textAlign: 'right' }} />
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button onClick={() => setCustomResult(calcScenario(customParams))}
              style={{ padding: '5px 14px', background: COLORS.amber, color: '#000', border: 'none',
                fontFamily: FONT, fontSize: 10, letterSpacing: 1, cursor: 'pointer', fontWeight: 'bold' }}>
              CALCULATE
            </button>
          </div>
        </div>
        {customResult && (
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
              <tr>
                <td style={{ padding: '4px 8px', color: COLORS.cyan, fontSize: 10 }}>Custom scenario</td>
                <td style={{ padding: '4px 8px', textAlign: 'right',
                  color: customResult.priceChg >= 0 ? COLORS.green : COLORS.red }}>
                  {customResult.priceChg >= 0 ? '+' : ''}{customResult.priceChg.toFixed(2)}%
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: COLORS.textSecondary }}>
                  €{customResult.income.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: COLORS.textSecondary }}>
                  {customResult.totalGross >= 0 ? '+' : ''}{customResult.totalGross.toFixed(2)}%
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', fontWeight: 'bold',
                  color: customResult.totalNet >= targetNet ? COLORS.green : COLORS.red }}>
                  {customResult.totalNet >= 0 ? '+' : ''}{customResult.totalNet.toFixed(2)}%
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', fontSize: 10,
                  color: recoveryColor(customResult.recoveryMonths) }}>
                  {customResult.recoveryMonths > 0 ? customResult.recoveryMonths.toFixed(1) + 'mo' : '—'}
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </div>

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
