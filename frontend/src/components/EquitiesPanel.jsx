import { useState, useEffect, useMemo, useRef } from 'react';
import { COLORS, FONT } from '../utils/theme.js';
import { getSectorFactors } from '../utils/api.js';

const SECTORS = [
  'Energy',
  'Materials',
  'Industrials',
  'Consumer Disc',
  'Consumer Staples',
  'Health Care',
  'Financials',
  'Info Tech',
  'Comm Services',
  'Utilities',
  'Real Estate',
];

const LOOKBACK_OPTIONS = [
  { label: '1D', days: 1 },
  { label: '1W', days: 5 },
  { label: '2W', days: 10 },
  { label: '1M', days: 21 },
  { label: '3M', days: 63 },
  { label: '6M', days: 126 },
  { label: '1Y', days: 252 },
];

const RANGE_OPTIONS = ['1M', '3M', '6M', 'YTD', '1Y', '2Y', '5Y', '10Y', '15Y', '20Y', 'ALL'];

const MAIN_TABS = ['ATTRIBUTION', 'FACTORS', 'LEAD-LAG'];
const SUB_VIEWS = ['FACTOR PROFILE', 'ATTRIBUTION'];

const BASE_STYLE = {
  fontFamily: FONT,
  background: COLORS.bg,
  color: COLORS.white,
};

// ─── small reusable primitives ──────────────────────────────────────────────

function Divider() {
  return (
    <div
      style={{
        height: 1,
        background: COLORS.cardBorder,
        margin: '0',
      }}
    />
  );
}

function TabButton({ label, active, onClick, disabled }) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      style={{
        fontFamily: FONT,
        fontSize: 11,
        fontWeight: active ? 700 : 400,
        padding: '4px 12px',
        background: active ? COLORS.amber : COLORS.cardBorder,
        color: active ? COLORS.bgDark : disabled ? COLORS.textMuted : COLORS.textSecondary,
        border: `1px solid ${active ? COLORS.amber : COLORS.cardBorder}`,
        cursor: disabled ? 'not-allowed' : 'pointer',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        transition: 'background 0.1s, color 0.1s',
        outline: 'none',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {label}
    </button>
  );
}

function SectorButton({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: FONT,
        fontSize: 10,
        fontWeight: active ? 700 : 400,
        padding: '3px 9px',
        background: active ? COLORS.amber : '#1a1a1a',
        color: active ? COLORS.bgDark : COLORS.textSecondary,
        border: `1px solid ${active ? COLORS.amber : '#1a1a1a'}`,
        cursor: 'pointer',
        letterSpacing: '0.04em',
        outline: 'none',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  );
}

function LookbackButton({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: FONT,
        fontSize: 10,
        padding: '2px 8px',
        background: active ? COLORS.amber : '#1a1a1a',
        color: active ? COLORS.bgDark : COLORS.textSecondary,
        border: `1px solid ${active ? COLORS.amber : '#1a1a1a'}`,
        cursor: 'pointer',
        fontWeight: active ? 700 : 400,
        outline: 'none',
      }}
    >
      {label}
    </button>
  );
}

function RangeButton({ label }) {
  return (
    <button
      style={{
        fontFamily: FONT,
        fontSize: 10,
        padding: '2px 8px',
        background: '#1a1a1a',
        color: COLORS.textMuted,
        border: `1px solid #1a1a1a`,
        cursor: 'not-allowed',
        outline: 'none',
        opacity: 0.6,
      }}
      disabled
    >
      {label}
    </button>
  );
}

// ─── Sector Composition Bar ──────────────────────────────────────────────────

function SectorCompositionBar({ composition, lookbackLabel }) {
  const { market_pct = 0, sector_pct = 0, fundamental_pct = 0 } = composition || {};
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 6, letterSpacing: '0.04em' }}>
        SECTOR COMPOSITION ({lookbackLabel} returns) —{' '}
        <span style={{ color: COLORS.textSecondary, fontWeight: 400 }}>
          Weight-averaged factor exposure using {lookbackLabel} returns. Click any stock row to open
          full decomposition.
        </span>
      </div>
      <div
        style={{
          display: 'flex',
          width: '100%',
          height: 24,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${market_pct}%`,
            background: COLORS.blue,
            transition: 'width 0.4s ease',
          }}
        />
        <div
          style={{
            width: `${sector_pct}%`,
            background: COLORS.orange,
            transition: 'width 0.4s ease',
          }}
        />
        <div
          style={{
            width: `${fundamental_pct}%`,
            background: COLORS.pink,
            transition: 'width 0.4s ease',
          }}
        />
      </div>
      <div
        style={{
          display: 'flex',
          gap: 16,
          marginTop: 4,
          fontSize: 10,
          letterSpacing: '0.04em',
        }}
      >
        <span>
          <span style={{ color: COLORS.blue }}>MKT</span>
          <span style={{ color: COLORS.textSecondary }}> {market_pct}%</span>
        </span>
        <span>
          <span style={{ color: COLORS.orange }}>SEC</span>
          <span style={{ color: COLORS.textSecondary }}> {sector_pct}%</span>
        </span>
        <span>
          <span style={{ color: COLORS.pink }}>FUND</span>
          <span style={{ color: COLORS.textSecondary }}> {fundamental_pct}%</span>
        </span>
      </div>
    </div>
  );
}

// ─── Factor Profile Bars ─────────────────────────────────────────────────────

function FactorProfileBars({ stocks, onSelectStock }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8, letterSpacing: '0.04em' }}>
        FACTOR PROFILE —{' '}
        <span style={{ color: COLORS.textSecondary, fontWeight: 400 }}>
          Each bar shows MKT/SEC/FUND split. Click a stock to see full decomposition.
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {(stocks || []).slice(0, 20).map((stock) => {
          const mkt = stock.market_pct || 0;
          const sec = stock.sector_pct || 0;
          const fund = stock.fundamental_pct || 0;
          const total = mkt + sec + fund || 100;
          const mktW = (mkt / total) * 100;
          const secW = (sec / total) * 100;
          const fundW = (fund / total) * 100;

          return (
            <div
              key={stock.ticker}
              onClick={() => onSelectStock && onSelectStock(stock)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
              }}
            >
              {/* Ticker + Weight label */}
              <div
                style={{
                  width: 88,
                  textAlign: 'right',
                  fontSize: 10,
                  color: COLORS.white,
                  flexShrink: 0,
                  letterSpacing: '0.02em',
                }}
              >
                <span style={{ color: COLORS.white, fontWeight: 700 }}>{stock.ticker}</span>
                <span style={{ color: COLORS.textSecondary }}> {stock.weight?.toFixed(1)}%</span>
              </div>

              {/* Stacked bar */}
              <div
                style={{
                  flex: 1,
                  maxWidth: 500,
                  height: 14,
                  display: 'flex',
                  overflow: 'hidden',
                  background: '#111',
                }}
              >
                <div
                  style={{ width: `${mktW}%`, background: COLORS.blue, transition: 'width 0.3s' }}
                />
                <div
                  style={{ width: `${secW}%`, background: COLORS.orange, transition: 'width 0.3s' }}
                />
                <div
                  style={{ width: `${fundW}%`, background: COLORS.pink, transition: 'width 0.3s' }}
                />
              </div>

              {/* Split numbers */}
              <div style={{ fontSize: 10, letterSpacing: '0.02em', flexShrink: 0 }}>
                <span style={{ color: COLORS.blue }}>{mkt}</span>
                <span style={{ color: COLORS.textMuted }}>/</span>
                <span style={{ color: COLORS.orange }}>{sec}</span>
                <span style={{ color: COLORS.textMuted }}>/</span>
                <span style={{ color: COLORS.pink }}>{fund}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Stock Detail Table ──────────────────────────────────────────────────────

const COLUMNS = [
  { key: 'ticker', label: 'STOCK', align: 'left' },
  { key: 'weight', label: 'WEIGHT %', align: 'right' },
  { key: 'total_return', label: 'TOTAL RETURN', align: 'right' },
  { key: 'market_pct', label: 'MARKET %', align: 'right' },
  { key: 'sector_pct', label: 'SECTOR %', align: 'right' },
  { key: 'fundamental_pct', label: 'FUNDAMENTAL %', align: 'right' },
  { key: 'beta_market', label: 'BETA MKT', align: 'right' },
  { key: 'beta_sector', label: 'BETA SEC', align: 'right' },
  { key: 'r_squared', label: 'R²', align: 'right' },
  { key: '_sec_link', label: 'SEC', align: 'center', noSort: true },
];

function InlineBar({ value, max = 100, color }) {
  const w = Math.min(Math.max((value / max) * 60, 0), 60);
  return (
    <div
      style={{
        display: 'inline-block',
        width: w,
        height: 6,
        background: color,
        marginLeft: 5,
        verticalAlign: 'middle',
        flexShrink: 0,
      }}
    />
  );
}

function StockDetailTable({ stocks, onSelectStock }) {
  const [sortKey, setSortKey] = useState('weight');
  const [sortDir, setSortDir] = useState('desc');
  const [hoverRow, setHoverRow] = useState(null);

  function handleHeaderClick(key) {
    if (key === '_sec_link') return;
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  const sorted = useMemo(() => {
    if (!stocks) return [];
    return [...stocks].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') {
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === 'asc' ? av - bv : bv - av;
    });
  }, [stocks, sortKey, sortDir]);

  const headerStyle = (col) => ({
    padding: '4px 8px',
    fontSize: 10,
    color: sortKey === col.key ? COLORS.amber : COLORS.textMuted,
    textAlign: col.align,
    letterSpacing: '0.06em',
    fontWeight: 700,
    cursor: col.noSort ? 'default' : 'pointer',
    userSelect: 'none',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    whiteSpace: 'nowrap',
    background: COLORS.bgDark,
  });

  return (
    <div id="stock-detail-table" style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8, letterSpacing: '0.04em' }}>
        STOCK DETAIL —{' '}
        <span style={{ color: COLORS.textSecondary, fontWeight: 400 }}>
          Click headers to sort, click rows to open 3-factor popup.
        </span>
      </div>
      <div style={{ overflowX: 'auto', width: '100%' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 11,
            fontFamily: FONT,
          }}
        >
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  style={headerStyle(col)}
                  onClick={() => handleHeaderClick(col.key)}
                >
                  {col.label}
                  {!col.noSort && sortKey === col.key && (
                    <span style={{ marginLeft: 4, color: COLORS.amber }}>
                      {sortDir === 'asc' ? '▲' : '▼'}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((stock, i) => {
              const isHovered = hoverRow === stock.ticker;
              const rowBg = isHovered ? '#111' : i % 2 === 0 ? COLORS.card : 'transparent';

              const returnPos =
                typeof stock.total_return === 'number' ? stock.total_return >= 0 : true;
              const returnColor = returnPos ? COLORS.green : COLORS.red;
              const returnLabel = stock.total_return_pct || `${stock.total_return?.toFixed(1)}%`;

              const betaMktColor =
                stock.beta_market > 1.2
                  ? COLORS.amber
                  : stock.beta_market < 0.8
                  ? COLORS.green
                  : COLORS.white;
              const r2Color =
                stock.r_squared > 0.7
                  ? COLORS.green
                  : stock.r_squared < 0.3
                  ? COLORS.red
                  : COLORS.white;

              const cellStyle = {
                padding: '4px 8px',
                borderBottom: `1px solid ${COLORS.cardBorder}`,
                background: rowBg,
                transition: 'background 0.1s',
                whiteSpace: 'nowrap',
              };

              return (
                <tr
                  key={stock.ticker}
                  onMouseEnter={() => setHoverRow(stock.ticker)}
                  onMouseLeave={() => setHoverRow(null)}
                  onClick={() => onSelectStock && onSelectStock(stock)}
                  style={{ cursor: 'pointer' }}
                >
                  {/* STOCK */}
                  <td style={{ ...cellStyle, textAlign: 'left', color: COLORS.white, fontWeight: 700 }}>
                    {stock.ticker}
                  </td>
                  {/* WEIGHT */}
                  <td style={{ ...cellStyle, textAlign: 'right', color: COLORS.white }}>
                    {stock.weight?.toFixed(1)}
                  </td>
                  {/* TOTAL RETURN */}
                  <td style={{ ...cellStyle, textAlign: 'right', color: returnColor }}>
                    {returnLabel}
                  </td>
                  {/* MARKET % */}
                  <td style={{ ...cellStyle, textAlign: 'right' }}>
                    <span style={{ color: COLORS.blue }}>{stock.market_pct}</span>
                    <InlineBar value={stock.market_pct} color={COLORS.blue} />
                  </td>
                  {/* SECTOR % */}
                  <td style={{ ...cellStyle, textAlign: 'right' }}>
                    <span style={{ color: COLORS.orange }}>{stock.sector_pct}</span>
                    <InlineBar value={stock.sector_pct} color={COLORS.orange} />
                  </td>
                  {/* FUNDAMENTAL % */}
                  <td style={{ ...cellStyle, textAlign: 'right' }}>
                    <span style={{ color: COLORS.pink }}>{stock.fundamental_pct}</span>
                    <InlineBar value={stock.fundamental_pct} color={COLORS.pink} />
                  </td>
                  {/* BETA MKT */}
                  <td style={{ ...cellStyle, textAlign: 'right', color: betaMktColor }}>
                    {stock.beta_market?.toFixed(2)}
                  </td>
                  {/* BETA SEC */}
                  <td style={{ ...cellStyle, textAlign: 'right', color: COLORS.white }}>
                    {stock.beta_sector?.toFixed(2)}
                  </td>
                  {/* R-SQUARED */}
                  <td style={{ ...cellStyle, textAlign: 'right', color: r2Color }}>
                    {stock.r_squared?.toFixed(2)}
                  </td>
                  {/* SEC link */}
                  <td style={{ ...cellStyle, textAlign: 'center' }}>
                    <span
                      style={{
                        color: COLORS.cyan,
                        cursor: 'pointer',
                        textDecoration: 'underline',
                        fontSize: 10,
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      SEC
                    </span>
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

// ─── Stock Detail Popup ───────────────────────────────────────────────────────

function StockDetailPopup({ stock, onClose }) {
  if (!stock) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        fontFamily: FONT,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: COLORS.card,
          border: `1px solid ${COLORS.cardBorder}`,
          padding: 24,
          minWidth: 420,
          maxWidth: 560,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
          }}
        >
          <div>
            <span style={{ fontSize: 16, fontWeight: 700, color: COLORS.amber }}>
              {stock.ticker}
            </span>
            <span style={{ fontSize: 11, color: COLORS.textSecondary, marginLeft: 10 }}>
              Weight: {stock.weight?.toFixed(1)}%
            </span>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: '1px solid ' + COLORS.cardBorder,
              color: COLORS.textSecondary,
              cursor: 'pointer',
              fontFamily: FONT,
              fontSize: 12,
              padding: '2px 8px',
            }}
          >
            ✕
          </button>
        </div>

        <Divider />

        {/* Factor decomposition */}
        <div style={{ marginTop: 14, marginBottom: 14 }}>
          <div style={{ fontSize: 10, color: COLORS.textMuted, marginBottom: 10, letterSpacing: '0.06em' }}>
            3-FACTOR DECOMPOSITION
          </div>

          {[
            { label: 'MARKET', pct: stock.market_pct, contrib: stock.market_contribution, color: COLORS.blue },
            { label: 'SECTOR', pct: stock.sector_pct, contrib: stock.sector_contribution, color: COLORS.orange },
            { label: 'FUNDAMENTAL', pct: stock.fundamental_pct, contrib: stock.fundamental_contribution, color: COLORS.pink },
          ].map(({ label, pct, contrib, color }) => (
            <div key={label} style={{ marginBottom: 10 }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: 10,
                  marginBottom: 3,
                }}
              >
                <span style={{ color }}>{label}</span>
                <span style={{ color: COLORS.white }}>
                  {pct}%{' '}
                  <span style={{ color: COLORS.textSecondary }}>
                    (contrib: {contrib != null ? contrib.toFixed(1) : '—'})
                  </span>
                </span>
              </div>
              <div style={{ height: 8, background: '#111', width: '100%' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${pct}%`,
                    background: color,
                    transition: 'width 0.3s',
                  }}
                />
              </div>
            </div>
          ))}
        </div>

        <Divider />

        {/* Beta / R² stats */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 12,
            marginTop: 14,
          }}
        >
          {[
            { label: 'BETA MKT', value: stock.beta_market?.toFixed(2), color: stock.beta_market > 1.2 ? COLORS.amber : stock.beta_market < 0.8 ? COLORS.green : COLORS.white },
            { label: 'BETA SEC', value: stock.beta_sector?.toFixed(2), color: COLORS.white },
            { label: 'R²', value: stock.r_squared?.toFixed(2), color: stock.r_squared > 0.7 ? COLORS.green : stock.r_squared < 0.3 ? COLORS.red : COLORS.white },
            { label: 'ALPHA', value: stock.alpha != null ? `${stock.alpha > 0 ? '+' : ''}${stock.alpha.toFixed(1)}` : '—', color: stock.alpha > 0 ? COLORS.green : stock.alpha < 0 ? COLORS.red : COLORS.white },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 9, color: COLORS.textMuted, letterSpacing: '0.06em', marginBottom: 4 }}>
                {label}
              </div>
              <div style={{ fontSize: 16, fontWeight: 700, color }}>{value ?? '—'}</div>
            </div>
          ))}
        </div>

        {/* Total return */}
        <div
          style={{
            marginTop: 14,
            paddingTop: 12,
            borderTop: `1px solid ${COLORS.cardBorder}`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span style={{ fontSize: 10, color: COLORS.textMuted, letterSpacing: '0.06em' }}>
            TOTAL RETURN
          </span>
          <span
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: stock.total_return >= 0 ? COLORS.green : COLORS.red,
            }}
          >
            {stock.total_return_pct || `${stock.total_return?.toFixed(1)}%`}
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── Placeholder panels ───────────────────────────────────────────────────────

function PlaceholderPanel({ title, description }) {
  return (
    <div
      style={{
        padding: '48px 24px',
        textAlign: 'center',
        color: COLORS.textMuted,
        fontFamily: FONT,
      }}
    >
      <div style={{ fontSize: 14, color: COLORS.textSecondary, marginBottom: 8, letterSpacing: '0.08em' }}>
        {title}
      </div>
      <div style={{ fontSize: 11 }}>{description}</div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function EquitiesPanel() {
  const [mainTab, setMainTab] = useState('FACTORS');
  const [subView, setSubView] = useState('FACTOR PROFILE');
  const [selectedSector, setSelectedSector] = useState('Energy');
  const [lookbackIdx, setLookbackIdx] = useState(2); // default 2W = index 2
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedStock, setSelectedStock] = useState(null);
  const tableRef = useRef(null);

  const lookback = LOOKBACK_OPTIONS[lookbackIdx];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSectorFactors(selectedSector, lookback.days)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message || 'Failed to load data');
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedSector, lookback.days]);

  function scrollToTable() {
    const el = document.getElementById('stock-detail-table');
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  }

  return (
    <div style={{ ...BASE_STYLE, padding: 0, minHeight: '100%' }}>
      {/* ── Main Header ── */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '10px 16px',
          background: COLORS.bgDark,
          borderBottom: `1px solid ${COLORS.cardBorder}`,
        }}
      >
        <div>
          <span
            style={{
              fontSize: 16,
              fontWeight: 700,
              color: COLORS.amber,
              letterSpacing: '0.06em',
            }}
          >
            SECTOR ANALYSIS
          </span>
          <span style={{ fontSize: 12, color: COLORS.white, marginLeft: 12 }}>
            Per-stock factor decomposition &amp; attribution
          </span>
        </div>

        {/* Quick-access buttons */}
        <div style={{ display: 'flex', gap: 4 }}>
          {['BREADTH', 'DISPERSION'].map((label) => (
            <button
              key={label}
              disabled
              style={{
                fontFamily: FONT,
                fontSize: 10,
                padding: '3px 9px',
                background: '#1a1a1a',
                color: COLORS.textMuted,
                border: `1px solid ${COLORS.cardBorder}`,
                cursor: 'not-allowed',
                letterSpacing: '0.05em',
                opacity: 0.5,
                outline: 'none',
              }}
            >
              {label}
            </button>
          ))}
          <button
            onClick={scrollToTable}
            style={{
              fontFamily: FONT,
              fontSize: 10,
              padding: '3px 9px',
              background: '#1a1a1a',
              color: COLORS.cyan,
              border: `1px solid ${COLORS.cyan}`,
              cursor: 'pointer',
              letterSpacing: '0.05em',
              outline: 'none',
            }}
          >
            STOCK DETAIL
          </button>
          {['NEWS', 'FUNDAMENTALS'].map((label) => (
            <button
              key={label}
              disabled
              style={{
                fontFamily: FONT,
                fontSize: 10,
                padding: '3px 9px',
                background: '#1a1a1a',
                color: COLORS.textMuted,
                border: `1px solid ${COLORS.cardBorder}`,
                cursor: 'not-allowed',
                letterSpacing: '0.05em',
                opacity: 0.5,
                outline: 'none',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Main Sub-tabs: ATTRIBUTION / FACTORS / LEAD-LAG ── */}
      <div
        style={{
          display: 'flex',
          gap: 2,
          padding: '8px 16px',
          background: COLORS.bgDark,
          borderBottom: `1px solid ${COLORS.cardBorder}`,
        }}
      >
        {MAIN_TABS.map((tab) => (
          <TabButton
            key={tab}
            label={tab}
            active={mainTab === tab}
            onClick={() => setMainTab(tab)}
          />
        ))}
      </div>

      {/* ── Content area ── */}
      {mainTab !== 'FACTORS' ? (
        <PlaceholderPanel
          title={`${mainTab} — Coming soon`}
          description={
            mainTab === 'ATTRIBUTION'
              ? 'Return attribution by factor, time period, and contribution breakdown.'
              : 'Lead-lag cross-sector correlation and rotational signal analysis.'
          }
        />
      ) : (
        <div style={{ padding: '12px 16px' }}>
          {/* ── Sector selector ── */}
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 4,
              marginBottom: 10,
            }}
          >
            {SECTORS.map((s) => (
              <SectorButton
                key={s}
                label={s}
                active={selectedSector === s}
                onClick={() => setSelectedSector(s)}
              />
            ))}
          </div>

          {/* ETF ticker badge */}
          {data?.etf_ticker && (
            <div
              style={{
                fontSize: 10,
                color: COLORS.textMuted,
                marginBottom: 10,
                letterSpacing: '0.04em',
              }}
            >
              ETF:{' '}
              <span style={{ color: COLORS.cyan }}>{data.etf_ticker}</span>
            </div>
          )}

          {/* ── Sub-view tabs: FACTOR PROFILE / ATTRIBUTION ── */}
          <div style={{ display: 'flex', gap: 2, marginBottom: 12 }}>
            {SUB_VIEWS.map((v) => (
              <TabButton
                key={v}
                label={v}
                active={subView === v}
                onClick={() => setSubView(v)}
              />
            ))}
          </div>

          {/* ── Controls row ── */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 16,
              marginBottom: 16,
              flexWrap: 'wrap',
            }}
          >
            {/* Lookback */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span
                style={{
                  fontSize: 10,
                  color: COLORS.textMuted,
                  letterSpacing: '0.06em',
                  marginRight: 2,
                }}
              >
                LOOKBACK:
              </span>
              <div style={{ display: 'flex', gap: 2 }}>
                {LOOKBACK_OPTIONS.map((opt, i) => (
                  <LookbackButton
                    key={opt.label}
                    label={opt.label}
                    active={lookbackIdx === i}
                    onClick={() => setLookbackIdx(i)}
                  />
                ))}
              </div>
            </div>

            {/* Range (placeholder) */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span
                style={{
                  fontSize: 10,
                  color: COLORS.textMuted,
                  letterSpacing: '0.06em',
                  marginRight: 2,
                }}
              >
                RANGE:
              </span>
              <div style={{ display: 'flex', gap: 2 }}>
                {RANGE_OPTIONS.map((r) => (
                  <RangeButton key={r} label={r} />
                ))}
              </div>
            </div>
          </div>

          <Divider />
          <div style={{ marginTop: 16 }}>
            {/* ── Loading / Error states ── */}
            {loading && (
              <div
                style={{
                  padding: '40px 0',
                  textAlign: 'center',
                  color: COLORS.textSecondary,
                  fontSize: 12,
                  letterSpacing: '0.08em',
                }}
              >
                LOADING {selectedSector.toUpperCase()} DATA…
              </div>
            )}

            {error && !loading && (
              <div
                style={{
                  padding: '24px',
                  color: COLORS.red,
                  fontSize: 11,
                  background: '#1a0000',
                  border: `1px solid ${COLORS.red}`,
                  letterSpacing: '0.04em',
                }}
              >
                <span style={{ fontWeight: 700 }}>ERROR: </span>
                {error}
              </div>
            )}

            {!loading && !error && data && (
              <>
                {subView === 'FACTOR PROFILE' ? (
                  <>
                    <SectorCompositionBar
                      composition={data.sector_composition}
                      lookbackLabel={lookback.label}
                    />
                    <Divider />
                    <div style={{ marginTop: 14 }}>
                      <FactorProfileBars
                        stocks={data.stocks}
                        onSelectStock={setSelectedStock}
                      />
                    </div>
                    <Divider />
                    <div style={{ marginTop: 14 }}>
                      <StockDetailTable
                        stocks={data.stocks}
                        onSelectStock={setSelectedStock}
                      />
                    </div>
                  </>
                ) : (
                  <PlaceholderPanel
                    title="ATTRIBUTION — Coming soon"
                    description="Per-stock factor contribution and return attribution breakdown."
                  />
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Stock Detail Popup ── */}
      {selectedStock && (
        <StockDetailPopup
          stock={selectedStock}
          onClose={() => setSelectedStock(null)}
        />
      )}
    </div>
  );
}
