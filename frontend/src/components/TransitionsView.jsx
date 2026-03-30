import { COLORS, FONT, REGIME_COLORS, REGIME_LABELS } from '../utils/theme.js';

// ─── helpers ────────────────────────────────────────────────────────────────

function fmtPct(v, decimals = 3) {
  if (v == null || isNaN(v)) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${Number(v).toFixed(decimals)}%`;
}

function fmtBp(v) {
  if (v == null || isNaN(v)) return '—';
  const bp = Number(v).toFixed(1);
  return `${Number(bp) >= 0 ? '+' : ''}${bp}bp`;
}

function fmtSignal(v) {
  if (v == null || isNaN(v)) return '—';
  const sign = Number(v) >= 0 ? '+' : '';
  return `${sign}${Number(v).toFixed(2)}`;
}

function signColor(v, invert = false) {
  if (v == null || isNaN(v)) return COLORS.textSecondary;
  const pos = Number(v) >= 0;
  if (invert) return pos ? COLORS.red : COLORS.green;
  return pos ? COLORS.green : COLORS.red;
}

function getLinkageLabel(pct) {
  if (pct >= 60) return 'STRONGLY LINKED';
  if (pct >= 40) return 'MODERATELY LINKED';
  return 'WEAKLY LINKED';
}

function getLinkageColor(pct) {
  if (pct >= 60) return COLORS.amber;
  if (pct >= 40) return COLORS.yellow;
  return COLORS.textSecondary;
}

function getLinkageDesc(pct) {
  if (pct >= 60)
    return 'All 3 assets are being driven by the same theme. Regime signal is strong.';
  if (pct >= 40)
    return 'Assets are partially co-moving. Some mixed signals across the regime.';
  return 'Assets are moving independently. Regime signal is weak or noisy.';
}

function getLinkageTypical(median) {
  if (median >= 60) return 'typically linked';
  if (median >= 40) return 'typically moderate';
  return 'typically divergent';
}

// ─── styles (shared) ────────────────────────────────────────────────────────

const S = {
  panel: {
    background: COLORS.card,
    border: `1px solid ${COLORS.cardBorder}`,
    padding: '14px 16px',
    fontFamily: FONT,
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    overflow: 'hidden',
  },
  panelTitle: {
    fontSize: '11px',
    fontWeight: 700,
    letterSpacing: '0.12em',
    color: COLORS.textPrimary,
    textTransform: 'uppercase',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    paddingBottom: '6px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    flexWrap: 'wrap',
  },
  explainerText: {
    fontSize: '11px',
    color: COLORS.yellow,
    lineHeight: '1.5',
    opacity: 0.85,
  },
  tableWrap: {
    overflowX: 'auto',
    overflowY: 'auto',
    flex: 1,
  },
  th: {
    fontSize: '10px',
    color: COLORS.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    padding: '4px 8px',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    whiteSpace: 'nowrap',
    fontFamily: FONT,
    fontWeight: 600,
    background: COLORS.bgDark,
    textAlign: 'right',
  },
  thLeft: {
    textAlign: 'left',
  },
  td: {
    fontSize: '11px',
    padding: '5px 8px',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    whiteSpace: 'nowrap',
    fontFamily: FONT,
    textAlign: 'right',
    color: COLORS.white,
  },
  tdLeft: {
    textAlign: 'left',
  },
};

// ─── sub-components ─────────────────────────────────────────────────────────

function RegimeSquare({ regime, size = 10 }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        background: REGIME_COLORS[regime] || COLORS.textMuted,
        flexShrink: 0,
        marginRight: 5,
        verticalAlign: 'middle',
      }}
    />
  );
}

// ─── Panel 1: CURRENT STATE ──────────────────────────────────────────────────

function CurrentStatePanel({ data }) {
  const {
    current_regime,
    current_description,
    current_color,
    current_spx_metric,
    current_rates_metric,
    current_dxy_metric,
    current_linkage,
    linkage_label,
    regime_linkage,
  } = data;

  const regimeColor = current_color || REGIME_COLORS[current_regime] || COLORS.amber;
  const linkagePct = current_linkage ?? 0;
  const linkageLbl = getLinkageLabel(linkagePct);
  const linkageColor = getLinkageColor(linkagePct);
  const linkageDesc = getLinkageDesc(linkagePct);

  const regimeLinkageData = regime_linkage?.[current_regime];
  const medianLinkage = regimeLinkageData?.median_linkage ?? null;

  return (
    <div style={S.panel}>
      {/* Title */}
      <div style={S.panelTitle}>
        <span>CURRENT STATE</span>
        <span
          style={{
            color: regimeColor,
            background: `${regimeColor}18`,
            border: `1px solid ${regimeColor}55`,
            padding: '1px 7px',
            fontSize: '11px',
            letterSpacing: '0.1em',
          }}
        >
          {current_regime}
        </span>
      </div>

      {/* Description box */}
      <div
        style={{
          borderLeft: `3px solid ${regimeColor}`,
          background: `${regimeColor}0d`,
          padding: '8px 12px',
          color: regimeColor,
          fontSize: '12px',
          letterSpacing: '0.03em',
          lineHeight: '1.4',
        }}
      >
        {current_description || REGIME_LABELS[current_regime] || '—'}
      </div>

      {/* Signal row */}
      <div
        style={{
          display: 'flex',
          gap: '0',
          justifyContent: 'space-between',
        }}
      >
        {[
          { label: 'SPX SIGNAL', value: current_spx_metric, color: signColor(current_spx_metric) },
          { label: '10Y SIGNAL', value: current_rates_metric, color: COLORS.amber },
          { label: 'DXY SIGNAL', value: current_dxy_metric, color: COLORS.cyan },
        ].map(({ label, value, color }) => (
          <div
            key={label}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '4px',
              padding: '10px 6px',
              borderRight: `1px solid ${COLORS.cardBorder}`,
              background: COLORS.bgDark,
            }}
          >
            <span
              style={{
                fontSize: '9px',
                color: COLORS.textSecondary,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
              }}
            >
              {label}
            </span>
            <span
              style={{
                fontSize: '22px',
                fontWeight: 700,
                color,
                letterSpacing: '-0.01em',
                lineHeight: 1,
              }}
            >
              {fmtSignal(value)}
            </span>
          </div>
        ))}
        {/* last item no right border */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '4px',
            padding: '10px 6px',
            background: COLORS.bgDark,
          }}
        />
      </div>

      {/* Linkage box */}
      <div
        style={{
          border: `1px solid ${COLORS.cardBorder}`,
          background: COLORS.bgDark,
          padding: '10px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '5px',
        }}
      >
        <div
          style={{
            fontSize: '9px',
            color: COLORS.textSecondary,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
          }}
        >
          MARKET LINKAGE
        </div>
        <div
          style={{
            fontSize: '13px',
            fontWeight: 700,
            color: linkageColor,
            letterSpacing: '0.05em',
          }}
        >
          {linkageLbl} ({linkagePct.toFixed(0)}%)
        </div>
        <div
          style={{
            fontSize: '11px',
            color: COLORS.textSecondary,
            lineHeight: '1.5',
          }}
        >
          {linkageDesc}
        </div>
        {medianLinkage != null && (
          <div
            style={{
              fontSize: '10px',
              color: COLORS.textMuted,
              marginTop: '2px',
              borderTop: `1px solid ${COLORS.cardBorder}`,
              paddingTop: '5px',
            }}
          >
            Historical median linkage when in this regime:{' '}
            <span style={{ color: COLORS.textSecondary }}>
              {medianLinkage.toFixed(0)}%
            </span>{' '}
            ({getLinkageTypical(medianLinkage)})
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Panel 2: WHAT'S NEXT ────────────────────────────────────────────────────

function WhatsNextPanel({ data }) {
  const { current_regime, from_current } = data;

  const sorted = [...(from_current || [])].sort((a, b) => (b.prob ?? 0) - (a.prob ?? 0));

  return (
    <div style={S.panel}>
      {/* Title */}
      <div style={S.panelTitle}>
        <span>WHAT'S NEXT</span>
        <span style={{ color: COLORS.textMuted, fontSize: '10px', fontWeight: 400 }}>
          From {current_regime} — historical transition probabilities
        </span>
      </div>

      {/* Explainer */}
      <div style={S.explainerText}>
        How to read: PROB = chance of transitioning to that regime next. (stay) = staying in the
        current regime. SPX/10Y/DXY = median daily returns in the destination regime. LINKAGE = how
        correlated the 3 assets typically are in that regime.
      </div>

      {/* Table */}
      <div style={S.tableWrap}>
        <table
          style={{
            borderCollapse: 'collapse',
            width: '100%',
            tableLayout: 'auto',
          }}
        >
          <thead>
            <tr>
              {['TO', 'PROB', 'HIST. OBS', 'SPX', '10Y', 'DXY', 'LINKAGE'].map((h, i) => (
                <th
                  key={h}
                  style={{
                    ...S.th,
                    ...(i === 0 ? S.thLeft : {}),
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const probPct = row.prob ?? 0;
              const isHighProb = probPct > 50;
              const toLabel = row.is_stay
                ? `${row.to} (stay)`
                : `${row.to}`;
              const rowColor = row.color || REGIME_COLORS[row.to] || COLORS.textMuted;
              const linkagePct = row.linkage != null ? `${(row.linkage).toFixed(0)}%` : '—';

              return (
                <tr
                  key={row.to}
                  style={{
                    background: row.is_stay ? `${COLORS.amber}0a` : 'transparent',
                  }}
                >
                  {/* TO */}
                  <td style={{ ...S.td, ...S.tdLeft }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <RegimeSquare regime={row.to} size={9} />
                      <span style={{ color: rowColor, fontSize: '11px' }}>{toLabel}</span>
                    </span>
                  </td>
                  {/* PROB */}
                  <td style={{ ...S.td, color: COLORS.amber, fontWeight: isHighProb ? 700 : 400 }}>
                    {probPct.toFixed(1)}%
                  </td>
                  {/* HIST OBS */}
                  <td style={{ ...S.td, color: COLORS.textSecondary }}>
                    {row.hist_obs ?? '—'}
                  </td>
                  {/* SPX */}
                  <td style={{ ...S.td, color: signColor(row.spx_median) }}>
                    {fmtPct(row.spx_median)}
                  </td>
                  {/* 10Y — green when negative (yields down = good) */}
                  <td style={{ ...S.td, color: signColor(row.rates_median, true) }}>
                    {fmtBp(row.rates_median)}
                  </td>
                  {/* DXY */}
                  <td style={{ ...S.td, color: signColor(row.dxy_median) }}>
                    {fmtPct(row.dxy_median)}
                  </td>
                  {/* LINKAGE */}
                  <td style={{ ...S.td, color: COLORS.textSecondary }}>{linkagePct}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Panel 3: REGIME CHARACTERISTICS ────────────────────────────────────────

function RegimeCharacteristicsPanel({ data }) {
  const { current_regime, stats } = data;
  const currentLabel =
    REGIME_LABELS[current_regime] || current_regime || 'Regime Characteristics';

  const THEME_BAR_WIDTH = 180;

  return (
    <div style={S.panel}>
      {/* Title */}
      <div style={S.panelTitle}>
        <span>{current_regime}: REGIME CHARACTERISTICS</span>
      </div>

      {/* Explainer */}
      <div style={S.explainerText}>
        Y = median daily return while in that regime. LINKAGE = how much the assets move together in
        that regime. THEME = which asset drives the common move most (wider bar = bigger role).
      </div>

      {/* Table */}
      <div style={{ ...S.tableWrap, overflowY: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              {['REGIME', 'SPX', '10Y', 'DXY', 'LINKAGE', 'THEME (SPX / 10Y / DXY)'].map(
                (h, i) => (
                  <th
                    key={h}
                    style={{
                      ...S.th,
                      ...(i === 0 ? S.thLeft : {}),
                      ...(i === 5 ? { textAlign: 'left', minWidth: 220 } : {}),
                    }}
                  >
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {(stats || []).map((row) => {
              const regimeColor = row.color || REGIME_COLORS[row.regime] || COLORS.textMuted;
              const isCurrent = row.regime === current_regime;

              // Theme percentages
              const theme = row.theme || {};
              const spxT = theme.SPX ?? 0;
              const tenYT = theme['10Y'] ?? 0;
              const dxyT = theme.DXY ?? 0;
              const total = spxT + tenYT + dxyT || 1;
              const spxW = (spxT / total) * THEME_BAR_WIDTH;
              const tenYW = (tenYT / total) * THEME_BAR_WIDTH;
              const dxyW = (dxyT / total) * THEME_BAR_WIDTH;

              const linkagePct =
                row.linkage != null ? `${Number(row.linkage).toFixed(0)}%` : '—';

              return (
                <tr
                  key={row.regime}
                  style={{
                    background: isCurrent ? `${regimeColor}12` : 'transparent',
                  }}
                >
                  {/* REGIME */}
                  <td style={{ ...S.td, ...S.tdLeft }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <RegimeSquare regime={row.regime} size={9} />
                      <span
                        style={{
                          color: regimeColor,
                          fontWeight: isCurrent ? 700 : 400,
                          fontSize: '11px',
                        }}
                      >
                        {row.regime}
                      </span>
                    </span>
                  </td>
                  {/* SPX */}
                  <td style={{ ...S.td, color: signColor(row.spx_median) }}>
                    {fmtPct(row.spx_median)}
                  </td>
                  {/* 10Y */}
                  <td style={{ ...S.td, color: signColor(row.rates_median, true) }}>
                    {fmtBp(row.rates_median)}
                  </td>
                  {/* DXY */}
                  <td style={{ ...S.td, color: signColor(row.dxy_median) }}>
                    {fmtPct(row.dxy_median)}
                  </td>
                  {/* LINKAGE */}
                  <td style={{ ...S.td, color: COLORS.textSecondary }}>{linkagePct}</td>
                  {/* THEME bar */}
                  <td style={{ ...S.td, textAlign: 'left', padding: '5px 8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {/* stacked bar */}
                      <div
                        style={{
                          display: 'flex',
                          width: THEME_BAR_WIDTH,
                          height: 10,
                          flexShrink: 0,
                          background: COLORS.bgDark,
                          border: `1px solid ${COLORS.cardBorder}`,
                          overflow: 'hidden',
                        }}
                      >
                        <div
                          style={{
                            width: spxW,
                            background: COLORS.blue,
                            height: '100%',
                          }}
                        />
                        <div
                          style={{
                            width: tenYW,
                            background: COLORS.amber,
                            height: '100%',
                          }}
                        />
                        <div
                          style={{
                            width: dxyW,
                            background: COLORS.purple,
                            height: '100%',
                          }}
                        />
                      </div>
                      {/* percentage text */}
                      <span
                        style={{
                          fontSize: '10px',
                          color: COLORS.textMuted,
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {spxT.toFixed(0)}/{tenYT.toFixed(0)}/{dxyT.toFixed(0)}
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Panel 4: TRANSITION MATRIX ──────────────────────────────────────────────

function TransitionMatrixPanel({ data }) {
  const { transition_matrix } = data;

  if (!transition_matrix) {
    return (
      <div style={S.panel}>
        <div style={S.panelTitle}>TRANSITION MATRIX</div>
        <div style={{ color: COLORS.textMuted, fontSize: '11px' }}>No matrix data.</div>
      </div>
    );
  }

  const { matrix, counts, regimes } = transition_matrix;
  const n = regimes?.length ?? 0;

  return (
    <div style={S.panel}>
      {/* Title */}
      <div style={S.panelTitle}>
        <span>TRANSITION MATRIX</span>
        <span style={{ color: COLORS.textMuted, fontSize: '10px', fontWeight: 400 }}>
          P(row → col)
        </span>
      </div>

      {/* Explainer */}
      <div style={S.explainerText}>
        Each cell = % chance of going from the row regime to the column regime. Diagonal
        (highlighted) = how likely it is to stay in the same regime.
      </div>

      {/* Matrix table */}
      <div style={{ ...S.tableWrap, overflowX: 'auto', overflowY: 'auto' }}>
        <table
          style={{
            borderCollapse: 'collapse',
            tableLayout: 'fixed',
            fontSize: '10px',
            fontFamily: FONT,
          }}
        >
          <thead>
            <tr>
              {/* row-header spacer */}
              <th
                style={{
                  ...S.th,
                  width: 36,
                  minWidth: 36,
                  background: COLORS.bgDark,
                }}
              />
              {(regimes || []).map((r) => (
                <th
                  key={r}
                  style={{
                    ...S.th,
                    width: 44,
                    minWidth: 40,
                    color: REGIME_COLORS[r] || COLORS.textSecondary,
                    padding: '4px 4px',
                  }}
                >
                  {r}
                </th>
              ))}
              {/* STICK column header */}
              <th
                style={{
                  ...S.th,
                  width: 48,
                  minWidth: 44,
                  color: COLORS.amber,
                  padding: '4px 4px',
                }}
              >
                STICK
              </th>
            </tr>
          </thead>
          <tbody>
            {(regimes || []).map((rowRegime, ri) => {
              const rowColor = REGIME_COLORS[rowRegime] || COLORS.textMuted;
              const diagonalVal = matrix?.[ri]?.[ri] ?? 0;
              const diagonalPct = (diagonalVal * 100).toFixed(0) + '%';

              return (
                <tr key={rowRegime}>
                  {/* row label */}
                  <td
                    style={{
                      ...S.td,
                      ...S.tdLeft,
                      color: rowColor,
                      fontWeight: 600,
                      padding: '3px 6px',
                      background: COLORS.bgDark,
                      fontSize: '10px',
                    }}
                  >
                    {rowRegime}
                  </td>

                  {/* probability cells */}
                  {(regimes || []).map((colRegime, ci) => {
                    const val = matrix?.[ri]?.[ci] ?? 0;
                    const isDiag = ri === ci;
                    const pct = val * 100;
                    const bgAlpha = val * 0.3;

                    return (
                      <td
                        key={colRegime}
                        style={{
                          ...S.td,
                          fontSize: '10px',
                          padding: '3px 4px',
                          background: isDiag
                            ? `rgba(42, 42, 42, 0.9)`
                            : `rgba(212, 131, 10, ${bgAlpha})`,
                          color: isDiag ? COLORS.white : COLORS.textSecondary,
                          fontWeight: isDiag ? 700 : 400,
                          border: isDiag
                            ? `1px solid ${COLORS.amber}44`
                            : `1px solid ${COLORS.cardBorder}`,
                          textAlign: 'center',
                        }}
                      >
                        {pct.toFixed(0)}%
                      </td>
                    );
                  })}

                  {/* STICK column = diagonal value */}
                  <td
                    style={{
                      ...S.td,
                      fontSize: '10px',
                      padding: '3px 6px',
                      background: `rgba(212, 131, 10, 0.15)`,
                      color: COLORS.amber,
                      fontWeight: 700,
                      border: `1px solid ${COLORS.amber}44`,
                      textAlign: 'center',
                    }}
                  >
                    {diagonalPct}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function TransitionsView({ data, focus }) {
  if (!data) {
    return (
      <div
        style={{
          fontFamily: FONT,
          color: COLORS.textMuted,
          padding: '32px',
          fontSize: '13px',
          background: COLORS.bg,
          minHeight: '400px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        NO REGIME DATA
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gridTemplateRows: 'auto auto',
        gap: '2px',
        background: COLORS.bgDark,
        fontFamily: FONT,
        width: '100%',
        minHeight: 0,
      }}
    >
      <CurrentStatePanel data={data} />
      <WhatsNextPanel data={data} />
      <RegimeCharacteristicsPanel data={data} />
      <TransitionMatrixPanel data={data} />
    </div>
  );
}
