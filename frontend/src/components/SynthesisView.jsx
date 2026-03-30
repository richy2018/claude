import React, { useState, useEffect } from 'react';
import { COLORS, FONT, REGIME_COLORS } from '../utils/theme';
import { getSynthesis } from '../utils/api';

/* ─────────────────────────────────────────────────────────────
   Helper utilities
───────────────────────────────────────────────────────────── */

function fmtSigned(v, decimals = 2) {
  if (v == null) return '—';
  const n = parseFloat(v);
  return (n >= 0 ? '+' : '') + n.toFixed(decimals);
}

function fmtBp(v) {
  if (v == null) return null;
  const n = parseFloat(v);
  return (n >= 0 ? '+' : '') + n.toFixed(1);
}

function signColor(v) {
  if (v == null) return COLORS.textMuted;
  return parseFloat(v) >= 0 ? COLORS.green : COLORS.red;
}

/* ─────────────────────────────────────────────────────────────
   Sub-components
───────────────────────────────────────────────────────────── */

/**
 * PANEL 1 — STOCK-BOND REGIME
 */
function StockBondPanel({ synthesis }) {
  const current = synthesis?.stock_bond_regime || '';
  const spxMetric = synthesis?.spx_metric;
  const ratesMetric = synthesis?.rates_metric;

  const quadrants = [
    { key: 'GROWTH / INFLATION',   row: 0, col: 0 },
    { key: 'GOLDILOCKS / FED-PUT', row: 0, col: 1 },
    { key: 'STAGFLATION RISK',     row: 1, col: 0 },
    { key: 'FLIGHT TO SAFETY',     row: 1, col: 1 },
  ];

  function quadrantHighlightColor(key) {
    if (key === 'STAGFLATION RISK')     return COLORS.red;
    if (key === 'GOLDILOCKS / FED-PUT') return COLORS.green;
    if (key === 'GROWTH / INFLATION')   return COLORS.amber;
    if (key === 'FLIGHT TO SAFETY')     return COLORS.cyan;
    return COLORS.cardBorder;
  }

  return (
    <div style={{
      backgroundColor: COLORS.card,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: 14,
      display: 'flex',
      flexDirection: 'column',
      gap: 12,
    }}>
      {/* Panel title */}
      <div style={{ fontSize: 11, color: COLORS.amber, letterSpacing: 2, fontWeight: 'bold' }}>
        STOCK-BOND REGIME
      </div>

      {/* 2×2 quadrant grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
        {quadrants.map(({ key }) => {
          const isActive = current.toUpperCase() === key.toUpperCase();
          const hlColor = quadrantHighlightColor(key);
          return (
            <div
              key={key}
              style={{
                border: isActive ? `1px solid ${hlColor}` : `1px solid ${COLORS.cardBorder}`,
                backgroundColor: isActive ? `${hlColor}18` : 'transparent',
                padding: 12,
                textAlign: 'center',
                position: 'relative',
              }}
            >
              <div style={{
                fontSize: 10,
                letterSpacing: 1,
                color: isActive ? hlColor : COLORS.textMuted,
                lineHeight: 1.4,
                fontWeight: isActive ? 'bold' : 'normal',
              }}>
                {key}
              </div>
              {isActive && (
                <div style={{
                  fontSize: 9,
                  color: hlColor,
                  marginTop: 4,
                  letterSpacing: 1,
                  opacity: 0.8,
                }}>
                  CURRENT
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* SPX / 10Y signal values */}
      <div style={{ display: 'flex', gap: 20, paddingTop: 6, borderTop: `1px solid ${COLORS.cardBorder}` }}>
        <div>
          <span style={{ fontSize: 10, color: COLORS.textMuted, marginRight: 6 }}>SPX</span>
          <span style={{ fontSize: 13, fontWeight: 'bold', color: signColor(spxMetric) }}>
            {fmtSigned(spxMetric)}
          </span>
        </div>
        <div>
          <span style={{ fontSize: 10, color: COLORS.textMuted, marginRight: 6 }}>10Y</span>
          <span style={{ fontSize: 13, fontWeight: 'bold', color: signColor(ratesMetric) }}>
            {fmtSigned(ratesMetric)}
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * PANEL 2 — DOLLAR DURABILITY
 */
function DollarDurabilityPanel({ synthesis }) {
  const regime = synthesis?.dollar_regime || '';
  const text = synthesis?.dollar_text || '';
  const dxyLast = synthesis?.dxy_last;
  const dxyChg = synthesis?.dxy_chg;

  const isDurable = regime === 'DURABLE';
  const boxColor = isDurable ? COLORS.green : COLORS.red;
  const boxBg = isDurable ? `${COLORS.green}22` : `${COLORS.red}22`;

  return (
    <div style={{
      backgroundColor: COLORS.card,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: 14,
      display: 'flex',
      flexDirection: 'column',
      gap: 12,
    }}>
      {/* Panel title */}
      <div style={{ fontSize: 11, color: COLORS.amber, letterSpacing: 2, fontWeight: 'bold' }}>
        DOLLAR DURABILITY
      </div>

      {/* Main regime box */}
      <div style={{
        backgroundColor: boxBg,
        border: `1px solid ${boxColor}`,
        padding: '18px 12px',
        textAlign: 'center',
        flex: 1,
      }}>
        <div style={{
          fontSize: 28,
          fontWeight: 'bold',
          color: boxColor,
          letterSpacing: 3,
          lineHeight: 1,
        }}>
          {regime || '—'}
        </div>
      </div>

      {/* Dollar text explanation */}
      {text && (
        <div style={{
          fontSize: 12,
          color: COLORS.white,
          lineHeight: 1.5,
        }}>
          {text}
        </div>
      )}

      {/* DXY values */}
      <div style={{
        display: 'flex',
        gap: 20,
        paddingTop: 6,
        borderTop: `1px solid ${COLORS.cardBorder}`,
      }}>
        <div>
          <span style={{ fontSize: 10, color: COLORS.textMuted, marginRight: 6 }}>DXY</span>
          <span style={{ fontSize: 13, fontWeight: 'bold', color: COLORS.white }}>
            {dxyLast != null ? parseFloat(dxyLast).toFixed(2) : '—'}
          </span>
        </div>
        <div>
          <span style={{ fontSize: 10, color: COLORS.textMuted, marginRight: 6 }}>CHG</span>
          <span style={{ fontSize: 13, fontWeight: 'bold', color: signColor(dxyChg) }}>
            {fmtSigned(dxyChg)}
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * PANEL 3 — CURVE REGIME
 */
function CurveRegimePanel({ synthesis }) {
  const curveRegime = synthesis?.curve_regime || '—';
  const curveV = synthesis?.curve_v;
  const transitions = synthesis?.top_transitions || [];

  // Multiplier vs random chance (8 regimes)
  const randomProb = 100 / 8;

  function curveVColor(v) {
    if (v == null) return COLORS.textMuted;
    if (v >= 0.7) return COLORS.green;
    if (v >= 0.4) return COLORS.amber;
    return COLORS.textMuted;
  }

  return (
    <div style={{
      backgroundColor: COLORS.card,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: 14,
      display: 'flex',
      flexDirection: 'column',
      gap: 12,
    }}>
      {/* Panel title */}
      <div style={{ fontSize: 11, color: COLORS.amber, letterSpacing: 2, fontWeight: 'bold' }}>
        CURVE REGIME
      </div>

      {/* Regime name */}
      <div>
        <div style={{ fontSize: 24, fontWeight: 'bold', color: COLORS.white, letterSpacing: 1 }}>
          {curveRegime}
        </div>
        <div style={{ fontSize: 10, color: COLORS.textMuted, marginTop: 4 }}>
          2s10s nominal curve regime (20D lookback)
        </div>
      </div>

      {/* Curve-V */}
      {curveV != null && (
        <div style={{ fontSize: 12 }}>
          <span style={{ color: COLORS.textMuted }}>Curve-Cross Asset V: </span>
          <span style={{ color: curveVColor(curveV), fontWeight: 'bold' }}>
            {parseFloat(curveV).toFixed(2)}
          </span>
        </div>
      )}

      {/* Top transitions */}
      {transitions.length > 0 && (
        <div style={{
          borderTop: `1px solid ${COLORS.cardBorder}`,
          paddingTop: 10,
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}>
          <div style={{ fontSize: 10, color: COLORS.textMuted, letterSpacing: 1, marginBottom: 2 }}>
            TOP TRANSITIONS
          </div>
          {transitions.slice(0, 3).map((t, i) => {
            const prob = parseFloat(t.prob);
            const mult = (prob / randomProb).toFixed(1);
            const regimeColor = t.color || COLORS.textMuted;
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                <span style={{ color: COLORS.textMuted, minWidth: 32 }}>
                  {mult}x
                </span>
                <span style={{ color: COLORS.textMuted }}>→</span>
                <span style={{
                  display: 'inline-block',
                  width: 10,
                  height: 10,
                  backgroundColor: regimeColor,
                  flexShrink: 0,
                }} />
                <span style={{ color: regimeColor, fontWeight: 'bold' }}>
                  {t.to}
                </span>
                <span style={{ color: COLORS.textMuted }}>
                  ({Math.round(prob)}%)
                </span>
                {t.description && (
                  <span style={{ color: COLORS.textMuted, fontSize: 10, opacity: 0.7 }}>
                    — {t.description}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * SECTION 3 — MULTI-LOOKBACK RATE DECOMPOSITION TABLE
 */
function DecompositionTable({ decomposition }) {
  if (!decomposition || decomposition.length === 0) {
    return (
      <div style={{ color: COLORS.textMuted, fontSize: 12, padding: '16px 0' }}>
        No decomposition data available.
      </div>
    );
  }

  const periodGroups = [
    { label: '5D',  fields: ['5d_nom', '5d_real', '5d_infl'] },
    { label: '10D', fields: ['10d_nom', '10d_real', '10d_infl'] },
    { label: '20D', fields: ['20d_nom', '20d_real', '20d_infl'] },
    { label: '60D', fields: ['60d_nom', '60d_real', '60d_infl'] },
  ];

  const subHeaders = ['NOM', 'REAL', 'INFL'];

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: 11,
        fontFamily: FONT,
      }}>
        <thead>
          {/* Group header row */}
          <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
            <th style={{
              padding: '6px 10px',
              textAlign: 'left',
              color: COLORS.textMuted,
              fontSize: 10,
              fontWeight: 'normal',
              borderRight: `1px solid ${COLORS.cardBorder}`,
              minWidth: 52,
            }}>
              TENOR
            </th>
            {periodGroups.map(({ label }) => (
              <th
                key={label}
                colSpan={3}
                style={{
                  padding: '4px 8px',
                  textAlign: 'center',
                  color: COLORS.amber,
                  fontSize: 10,
                  fontWeight: 'bold',
                  letterSpacing: 1,
                  borderRight: `1px solid ${COLORS.cardBorder}`,
                  borderBottom: `1px solid ${COLORS.cardBorder}33`,
                }}
              >
                {label}
              </th>
            ))}
          </tr>
          {/* Sub-header row */}
          <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
            <th style={{
              padding: '4px 10px',
              borderRight: `1px solid ${COLORS.cardBorder}`,
            }} />
            {periodGroups.map(({ label }) =>
              subHeaders.map((sh) => (
                <th
                  key={`${label}-${sh}`}
                  style={{
                    padding: '4px 8px',
                    textAlign: 'right',
                    color: COLORS.textMuted,
                    fontSize: 10,
                    fontWeight: 'normal',
                    letterSpacing: 1,
                    borderRight: sh === 'INFL' ? `1px solid ${COLORS.cardBorder}` : 'none',
                    minWidth: 56,
                  }}
                >
                  {sh}
                </th>
              ))
            )}
          </tr>
        </thead>
        <tbody>
          {decomposition.map((row, i) => (
            <tr
              key={row.tenor || i}
              style={{
                borderBottom: `1px solid ${COLORS.cardBorder}`,
                backgroundColor: i % 2 === 0 ? 'transparent' : `${COLORS.bgDark}55`,
              }}
            >
              {/* Tenor label */}
              <td style={{
                padding: '6px 10px',
                color: COLORS.white,
                fontWeight: 'bold',
                fontSize: 12,
                borderRight: `1px solid ${COLORS.cardBorder}`,
                whiteSpace: 'nowrap',
              }}>
                {row.tenor}
              </td>

              {/* Data cells */}
              {periodGroups.map(({ fields }, gi) =>
                fields.map((field, fi) => {
                  const val = row[field];
                  const formatted = fmtBp(val);
                  const isLast = fi === fields.length - 1;
                  return (
                    <td
                      key={field}
                      style={{
                        padding: '6px 8px',
                        textAlign: 'right',
                        color: formatted != null ? (parseFloat(val) >= 0 ? COLORS.green : COLORS.red) : COLORS.textMuted,
                        borderRight: isLast ? `1px solid ${COLORS.cardBorder}` : 'none',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {formatted != null ? formatted : (
                        <span style={{ color: COLORS.textMuted }}>—</span>
                      )}
                    </td>
                  );
                })
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Main SynthesisView component
───────────────────────────────────────────────────────────── */

export default function SynthesisView({ regimeData, method, lookback, volWindow }) {
  const [synthesis, setSynthesis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function fetch() {
      setLoading(true);
      setError(null);
      try {
        const result = await getSynthesis({
          lookback,
          volWindow,
          volScaled: method === 'vol-scaled',
        });
        if (!cancelled) setSynthesis(result);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetch();
    return () => { cancelled = true; };
  }, [lookback, volWindow, method]);

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white, display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* ── Loading / Error states ── */}
      {loading && (
        <div style={{ padding: '20px 0', color: COLORS.amber, fontSize: 13 }}>
          Loading synthesis data...
        </div>
      )}
      {error && (
        <div style={{ padding: '12px 14px', border: `1px solid ${COLORS.red}44`, color: COLORS.red, fontSize: 13 }}>
          Error: {error}
        </div>
      )}

      {/* ════════════════════════════════════════════════════
          SECTION 1 — CURRENT STATE SYNTHESIS
      ═════════════════════════════════════════════════════ */}
      <section>
        {/* Section title */}
        <div style={{ marginBottom: 12 }}>
          <span style={{ fontSize: 13, color: COLORS.amber, fontWeight: 'bold', letterSpacing: 2 }}>
            CURRENT STATE SYNTHESIS
          </span>
          <span style={{ fontSize: 11, color: COLORS.textMuted, marginLeft: 10 }}>
            — All signals connected
          </span>
        </div>

        {/* 3 panels */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          <StockBondPanel synthesis={synthesis} />
          <DollarDurabilityPanel synthesis={synthesis} />
          <CurveRegimePanel synthesis={synthesis} />
        </div>
      </section>

      {/* ════════════════════════════════════════════════════
          SECTION 2 — TRADING USE guidance block
      ═════════════════════════════════════════════════════ */}
      <section style={{
        backgroundColor: COLORS.card,
        border: `1px solid ${COLORS.cardBorder}`,
        padding: '10px 14px',
      }}>
        <div style={{
          fontSize: 11,
          color: COLORS.yellow,
          lineHeight: 1.65,
        }}>
          <span style={{ fontWeight: 'bold', letterSpacing: 1 }}>TRADING USE: </span>
          Read all three panels together as a single diagnosis. Example: &lsquo;GOLDILOCKS (stocks up, rates down) + dollar DURABLE + Bull Flattener mapping to R4 with 1.8x lift&rsquo; = coherent, high-conviction setup for long risk / long duration. When signals conflict (e.g. stock-bond says GOLDILOCKS but dollar says RICH): lower conviction, tighter stops, smaller position sizes. The conflict itself is the signal — it means something in the macro picture is inconsistent and one leg will likely converge. Signal strength (the vol-scaled number) tells you conviction: +/- 0.15 is barely above zero (marginal), +/- 2.5 is extreme.
        </div>
      </section>

      {/* ════════════════════════════════════════════════════
          SECTION 3 — MULTI-LOOKBACK RATE DECOMPOSITION
      ═════════════════════════════════════════════════════ */}
      <section>
        {/* Section title */}
        <div style={{ marginBottom: 12 }}>
          <span style={{ fontSize: 13, color: COLORS.amber, fontWeight: 'bold', letterSpacing: 2 }}>
            MULTI-LOOKBACK RATE DECOMPOSITION
          </span>
          <span style={{ fontSize: 11, color: COLORS.textMuted, marginLeft: 10 }}>
            — Real vs inflation attribution at every tenor across all lookbacks
          </span>
        </div>

        <div style={{
          backgroundColor: COLORS.card,
          border: `1px solid ${COLORS.cardBorder}`,
          padding: 12,
        }}>
          {synthesis ? (
            <DecompositionTable decomposition={synthesis.decomposition} />
          ) : (
            !loading && (
              <div style={{ color: COLORS.textMuted, fontSize: 12, padding: '12px 0' }}>
                No data loaded.
              </div>
            )
          )}
        </div>
      </section>

    </div>
  );
}
