import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme.js';
import { getSectorFactors, getStockLookup } from '../utils/api.js';

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

const MAIN_TABS = ['ATTRIBUTION', 'FACTORS', 'LEAD-LAG', 'STOCK LOOKUP'];
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
        background: active ? COLORS.amber : COLORS.bg,
        color: active ? COLORS.bgDark : COLORS.textSecondary,
        border: `1px solid ${active ? COLORS.amber : COLORS.bg}`,
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
        background: active ? COLORS.amber : COLORS.bg,
        color: active ? COLORS.bgDark : COLORS.textSecondary,
        border: `1px solid ${active ? COLORS.amber : COLORS.bg}`,
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
        background: COLORS.bg,
        color: COLORS.textMuted,
        border: `1px solid ${COLORS.bg}`,
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
            background: COLORS.factorMkt,
            transition: 'width 0.4s ease',
          }}
        />
        <div
          style={{
            width: `${sector_pct}%`,
            background: COLORS.factorSec,
            transition: 'width 0.4s ease',
          }}
        />
        <div
          style={{
            width: `${fundamental_pct}%`,
            background: COLORS.factorFund,
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
          <span style={{ color: COLORS.factorMkt }}>MKT</span>
          <span style={{ color: COLORS.textSecondary }}> {market_pct}%</span>
        </span>
        <span>
          <span style={{ color: COLORS.factorSec }}>SEC</span>
          <span style={{ color: COLORS.textSecondary }}> {sector_pct}%</span>
        </span>
        <span>
          <span style={{ color: COLORS.factorFund }}>FUND</span>
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
          Each bar shows contribution by factor. Green = positive, Red = negative. Click a stock for detail.
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {(stocks || []).slice(0, 20).map((stock) => {
          const mkt = stock.market_contribution || 0;
          const sec = stock.sector_contribution || 0;
          const fund = stock.fundamental_contribution || 0;
          const maxAbs = Math.max(Math.abs(mkt), Math.abs(sec), Math.abs(fund), 0.01);

          return (
            <div
              key={stock.ticker}
              onClick={() => onSelectStock && onSelectStock(stock)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
            >
              <div style={{ width: 88, textAlign: 'right', fontSize: 10, flexShrink: 0 }}>
                <span style={{ color: COLORS.white, fontWeight: 700 }}>{stock.ticker}</span>
                <span style={{ color: COLORS.textSecondary }}> {stock.weight?.toFixed(1)}%</span>
              </div>

              {/* Three contribution bars side by side */}
              <div style={{ flex: 1, maxWidth: 500, display: 'flex', gap: 2 }}>
                {[mkt, sec, fund].map((val, i) => {
                  const isNeg = val < 0;
                  const factorColors = [COLORS.factorMkt, COLORS.factorSec, COLORS.factorFund];
                  const barColor = isNeg ? COLORS.factorFundNeg : factorColors[i];
                  const barW = (Math.abs(val) / maxAbs) * 100;
                  return (
                    <div key={i} style={{ flex: 1, height: 12, background: COLORS.bgDark, position: 'relative', overflow: 'hidden' }}>
                      <div style={{
                        position: 'absolute', height: '100%',
                        width: `${barW}%`,
                        left: isNeg ? `${100 - barW}%` : 0,
                        background: barColor,
                        opacity: isNeg ? 0.8 : 1,
                        boxShadow: `0 0 4px ${barColor}44`,
                      }} />
                    </div>
                  );
                })}
              </div>

              {/* Contribution numbers */}
              <div style={{ fontSize: 10, flexShrink: 0, display: 'flex', gap: 4, minWidth: 120, justifyContent: 'flex-end' }}>
                {[mkt, sec, fund].map((val, i) => {
                  const factorColors = [COLORS.factorMkt, COLORS.factorSec, COLORS.factorFund];
                  const color = val < 0 ? COLORS.factorFundNeg : factorColors[i];
                  return (
                    <span key={i} style={{ color, minWidth: 36, textAlign: 'right' }}>
                      {val >= 0 ? '+' : ''}{val.toFixed(1)}
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })}
        <div style={{ fontSize: 9, marginTop: 4, display: 'flex', gap: 16, paddingLeft: 96 }}>
          <span style={{ color: COLORS.factorMkt }}>MKT</span>
          <span style={{ color: COLORS.factorSec }}>SEC</span>
          <span style={{ color: COLORS.factorFund }}>FUND/ALPHA</span>
        </div>
      </div>
    </div>
  );
}

// ─── Stock Detail Table ──────────────────────────────────────────────────────

const COLUMNS = [
  { key: 'ticker', label: 'STOCK', align: 'left' },
  { key: 'weight', label: 'WEIGHT %', align: 'right' },
  { key: 'total_return', label: 'TOTAL RETURN', align: 'right' },
  { key: 'market_contribution', label: 'MARKET', align: 'right' },
  { key: 'sector_contribution', label: 'SECTOR', align: 'right' },
  { key: 'fundamental_contribution', label: 'FUND/ALPHA', align: 'right' },
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
              const rowBg = isHovered ? COLORS.cardAlt : i % 2 === 0 ? COLORS.card : 'transparent';

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
                  {/* MARKET / SECTOR / FUNDAMENTAL contributions */}
                  {['market_contribution', 'sector_contribution', 'fundamental_contribution'].map((key, idx) => {
                    const val = stock[key] || 0;
                    const isNeg = val < 0;
                    const factorColors = [COLORS.factorMkt, COLORS.factorSec, COLORS.factorFund];
                    const barColor = isNeg ? COLORS.factorFundNeg : factorColors[idx];
                    const maxAbs = Math.max(
                      Math.abs(stock.market_contribution || 0),
                      Math.abs(stock.sector_contribution || 0),
                      Math.abs(stock.fundamental_contribution || 0),
                      0.01
                    );
                    const barW = Math.min((Math.abs(val) / maxAbs) * 40, 40);
                    return (
                      <td key={key} style={{ ...cellStyle, textAlign: 'right', minWidth: 90 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                          <div style={{ width: 44, height: 8, background: COLORS.bgDark, position: 'relative', flexShrink: 0 }}>
                            <div style={{
                              position: 'absolute', height: '100%',
                              width: barW, right: isNeg ? undefined : 0, left: isNeg ? 0 : undefined,
                              background: barColor,
                              boxShadow: `0 0 4px ${barColor}44`,
                            }} />
                          </div>
                          <span style={{ color: barColor, fontSize: 10, minWidth: 32, textAlign: 'right' }}>
                            {val >= 0 ? '+' : ''}{val.toFixed(1)}
                          </span>
                        </div>
                      </td>
                    );
                  })}
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

          {(() => {
            const factors = [
              { label: 'MARKET', contrib: stock.market_contribution, color: COLORS.factorMkt },
              { label: 'SECTOR', contrib: stock.sector_contribution, color: COLORS.factorSec },
              { label: 'FUND/ALPHA', contrib: stock.fundamental_contribution, color: COLORS.factorFund },
            ];
            const maxAbs = Math.max(...factors.map(f => Math.abs(f.contrib || 0)), 0.01);

            return factors.map(({ label, contrib, color }) => {
              const val = contrib || 0;
              const barWidth = (Math.abs(val) / maxAbs) * 50;
              const isNeg = val < 0;
              const barColor = isNeg ? COLORS.factorFundNeg : color;

              return (
                <div key={label} style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 3 }}>
                    <span style={{ color }}>{label}</span>
                    <span style={{ color: barColor, fontWeight: 'bold' }}>
                      {val >= 0 ? '+' : ''}{val.toFixed(1)}
                    </span>
                  </div>
                  <div style={{ height: 10, background: COLORS.cardAlt, width: '100%', position: 'relative', overflow: 'hidden' }}>
                    {/* Center line */}
                    <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: COLORS.textMuted, opacity: 0.4, zIndex: 1 }} />
                    {/* Glowing bar */}
                    <div style={{
                      position: 'absolute',
                      height: '100%',
                      width: `${barWidth}%`,
                      left: isNeg ? `${50 - barWidth}%` : '50%',
                      background: barColor,
                      boxShadow: `0 0 8px ${barColor}66, 0 0 16px ${barColor}33`,
                      transition: 'width 0.3s, left 0.3s',
                    }} />
                  </div>
                </div>
              );
            });
          })()}

          <div style={{ fontSize: 9, color: COLORS.textMuted, marginTop: 4, textAlign: 'center' }}>
            Total: {((stock.market_contribution || 0) + (stock.sector_contribution || 0) + (stock.fundamental_contribution || 0)).toFixed(1)} = Return
          </div>
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

// ─── Stock Lookup Panel ──────────────────────────────────────────────────────

function StockLookupPanel() {
  const [ticker, setTicker] = useState('');
  const [lookbackIdx, setLookbackIdx] = useState(2);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const lookback = LOOKBACK_OPTIONS[lookbackIdx];

  const doLookup = useCallback((overrideTicker) => {
    const t = (overrideTicker || ticker).trim().toUpperCase();
    if (!t) return;
    setLoading(true);
    setError(null);
    getStockLookup(t, lookback.days)
      .then((d) => {
        if (d.error) {
          setError(d.error);
          setData(null);
        } else {
          setData(d);
        }
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Ticker not found. Check symbol and try again.');
        setData(null);
        setLoading(false);
      });
  }, [ticker, lookback.days]);

  // Re-fetch when lookback changes and we already have data
  useEffect(() => {
    if (data?.ticker) {
      doLookup(data.ticker);
    }
  }, [lookback.days]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleKeyDown(e) {
    if (e.key === 'Enter') doLookup();
  }

  const decomp = data ? [
    { label: 'MKT', value: data.market_contribution, color: COLORS.factorMkt },
    { label: 'SEC', value: data.sector_contribution, color: COLORS.factorSec },
    { label: 'FUND', value: data.fundamental_contribution, color: COLORS.factorFund },
  ] : [];

  const totalAbs = decomp.reduce((s, d) => s + Math.abs(d.value || 0), 0) || 1;

  return (
    <div style={{ padding: '12px 16px' }}>
      {/* ── Input Section ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onKeyDown={handleKeyDown}
            placeholder="Enter ticker (e.g., AAPL, MSFT, NVDA)"
            style={{
              fontFamily: FONT,
              fontSize: 12,
              padding: '6px 12px',
              background: COLORS.card,
              color: COLORS.white,
              border: `1px solid ${COLORS.cardBorder}`,
              outline: 'none',
              width: 280,
              letterSpacing: '0.04em',
            }}
          />
          <button
            onClick={() => doLookup()}
            disabled={!ticker.trim() || loading}
            style={{
              fontFamily: FONT,
              fontSize: 11,
              fontWeight: 700,
              padding: '6px 16px',
              background: ticker.trim() ? COLORS.amber : COLORS.cardBorder,
              color: ticker.trim() ? COLORS.bgDark : COLORS.textMuted,
              border: `1px solid ${ticker.trim() ? COLORS.amber : COLORS.cardBorder}`,
              cursor: ticker.trim() && !loading ? 'pointer' : 'not-allowed',
              letterSpacing: '0.06em',
              outline: 'none',
            }}
          >
            {loading ? 'LOADING…' : 'SEARCH'}
          </button>
        </div>

        {/* Lookback selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 10, color: COLORS.textMuted, letterSpacing: '0.06em' }}>
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
      </div>

      {/* ── Error ── */}
      {error && !loading && (
        <div style={{
          padding: '16px', color: COLORS.red, fontSize: 11,
          background: '#1a0000', border: `1px solid ${COLORS.red}`,
          letterSpacing: '0.04em', marginBottom: 16,
        }}>
          <span style={{ fontWeight: 700 }}>ERROR: </span>{error}
        </div>
      )}

      {/* ── Loading ── */}
      {loading && (
        <div style={{
          padding: '40px 0', textAlign: 'center', color: COLORS.textSecondary,
          fontSize: 12, letterSpacing: '0.08em',
        }}>
          LOADING {ticker.toUpperCase()} DATA…
        </div>
      )}

      {/* ── Results ── */}
      {!loading && !error && data && (
        <div>
          {/* Header */}
          <div style={{
            display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12,
          }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: COLORS.amber }}>
              {data.ticker}
            </span>
            <span style={{ fontSize: 11, color: COLORS.textMuted }}>
              {data.sector || 'Unknown'} · ETF: <span style={{ color: COLORS.cyan }}>{data.sector_etf}</span>
            </span>
            <span style={{
              fontSize: 14, fontWeight: 700, marginLeft: 'auto',
              color: data.total_return >= 0 ? COLORS.green : COLORS.red,
            }}>
              {data.total_return_pct} ({lookback.label})
            </span>
          </div>

          <Divider />

          {/* ── 1. Return Decomposition Bar ── */}
          <div style={{ marginTop: 14, marginBottom: 16 }}>
            <div style={{
              fontSize: 11, color: COLORS.amber, marginBottom: 8, letterSpacing: '0.04em',
            }}>
              RETURN DECOMPOSITION ({lookback.label}) —{' '}
              <span style={{ color: COLORS.textSecondary, fontWeight: 400 }}>
                Total return split into Market, Sector, and Alpha components
              </span>
            </div>

            {/* Stacked horizontal bar */}
            <div style={{ display: 'flex', width: '100%', height: 28, overflow: 'hidden', marginBottom: 6 }}>
              {decomp.map((d) => {
                const pct = (Math.abs(d.value) / totalAbs) * 100;
                return (
                  <div key={d.label} style={{
                    width: `${pct}%`,
                    background: d.value < 0 ? COLORS.factorFundNeg : d.color,
                    transition: 'width 0.4s ease',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 9, color: COLORS.bgDark, fontWeight: 700,
                    minWidth: pct > 8 ? 'auto' : 0,
                    overflow: 'hidden',
                  }}>
                    {pct > 10 ? `${d.label} ${d.value >= 0 ? '+' : ''}${d.value.toFixed(1)}` : ''}
                  </div>
                );
              })}
            </div>

            {/* Legend */}
            <div style={{ display: 'flex', gap: 16, fontSize: 10 }}>
              {decomp.map((d) => (
                <span key={d.label}>
                  <span style={{ color: d.value < 0 ? COLORS.factorFundNeg : d.color }}>
                    {d.label}
                  </span>
                  <span style={{ color: COLORS.textSecondary }}>
                    {' '}{d.value >= 0 ? '+' : ''}{d.value.toFixed(2)}
                  </span>
                </span>
              ))}
            </div>
          </div>

          <Divider />

          {/* ── 2. Factor Detail Table ── */}
          <div style={{ marginTop: 14, marginBottom: 16 }}>
            <div style={{
              fontSize: 11, color: COLORS.amber, marginBottom: 8, letterSpacing: '0.04em',
            }}>
              FACTOR DETAIL
            </div>

            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr',
              gap: 0, fontSize: 11, maxWidth: 480,
            }}>
              {[
                { label: 'Ticker', value: data.ticker, color: COLORS.white },
                { label: `Total Return (${lookback.label})`, value: data.total_return_pct, color: data.total_return >= 0 ? COLORS.green : COLORS.red },
                { label: 'Market Contribution', value: `${data.market_contribution >= 0 ? '+' : ''}${data.market_contribution.toFixed(2)}%`, color: COLORS.factorMkt },
                { label: 'Sector Contribution', value: `${data.sector_contribution >= 0 ? '+' : ''}${data.sector_contribution.toFixed(2)}%`, color: COLORS.factorSec },
                { label: 'Fund/Alpha (residual)', value: `${data.fundamental_contribution >= 0 ? '+' : ''}${data.fundamental_contribution.toFixed(2)}%`, color: data.fundamental_contribution >= 0 ? COLORS.factorFund : COLORS.factorFundNeg },
                { label: 'Beta (Market)', value: data.beta_market.toFixed(2), color: data.beta_market > 1.2 ? COLORS.amber : data.beta_market < 0.8 ? COLORS.green : COLORS.white },
                { label: 'Beta (Sector)', value: data.beta_sector.toFixed(2), color: COLORS.white },
                { label: 'R²', value: data.r_squared.toFixed(2), color: data.r_squared > 0.7 ? COLORS.green : data.r_squared < 0.3 ? COLORS.red : COLORS.white },
              ].map(({ label, value, color }, i) => (
                <div key={label} style={{
                  display: 'flex', justifyContent: 'space-between',
                  padding: '5px 10px',
                  background: i % 2 === 0 ? COLORS.card : 'transparent',
                  borderBottom: `1px solid ${COLORS.cardBorder}`,
                }}>
                  <span style={{ color: COLORS.textMuted }}>{label}</span>
                  <span style={{ color, fontWeight: 600 }}>{value}</span>
                </div>
              ))}
            </div>
          </div>

          <Divider />

          {/* ── 3. Historical Factor Chart ── */}
          {data.history && data.history.length > 1 && (
            <div style={{ marginTop: 14 }}>
              <div style={{
                fontSize: 11, color: COLORS.amber, marginBottom: 8, letterSpacing: '0.04em',
              }}>
                HISTORICAL FACTOR CONTRIBUTIONS ({lookback.label}) —{' '}
                <span style={{ color: COLORS.textSecondary, fontWeight: 400 }}>
                  Cumulative daily Market, Sector, and Alpha contributions
                </span>
              </div>

              <div style={{ width: '100%', height: 280 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.history} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
                      tickFormatter={(d) => d.slice(5)} // MM-DD
                      stroke={COLORS.cardBorder}
                    />
                    <YAxis
                      tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
                      tickFormatter={(v) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`}
                      stroke={COLORS.cardBorder}
                      width={50}
                    />
                    <Tooltip
                      contentStyle={{
                        background: COLORS.card,
                        border: `1px solid ${COLORS.cardBorder}`,
                        fontFamily: FONT,
                        fontSize: 10,
                        color: COLORS.white,
                      }}
                      formatter={(val, name) => [`${val > 0 ? '+' : ''}${val.toFixed(2)}%`, name]}
                      labelFormatter={(label) => label}
                    />
                    <Legend
                      wrapperStyle={{ fontSize: 10, fontFamily: FONT }}
                    />
                    <Line
                      type="monotone" dataKey="total" name="Total"
                      stroke={COLORS.white} strokeWidth={2} dot={false}
                      strokeDasharray="4 2"
                    />
                    <Line
                      type="monotone" dataKey="market" name="Market"
                      stroke={COLORS.factorMkt} strokeWidth={1.5} dot={false}
                    />
                    <Line
                      type="monotone" dataKey="sector" name="Sector"
                      stroke={COLORS.factorSec} strokeWidth={1.5} dot={false}
                    />
                    <Line
                      type="monotone" dataKey="alpha" name="Alpha"
                      stroke={COLORS.factorFund} strokeWidth={1.5} dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Empty state ── */}
      {!loading && !error && !data && (
        <div style={{
          padding: '48px 24px', textAlign: 'center', color: COLORS.textMuted, fontFamily: FONT,
        }}>
          <div style={{ fontSize: 14, color: COLORS.textSecondary, marginBottom: 8, letterSpacing: '0.08em' }}>
            SINGLE STOCK FACTOR DECOMPOSITION
          </div>
          <div style={{ fontSize: 11 }}>
            Enter a ticker symbol above to decompose its returns into Market, Sector, and Alpha components using the same MFRA methodology.
          </div>
        </div>
      )}
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
                background: COLORS.bg,
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
              background: COLORS.bg,
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
                background: COLORS.bg,
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
      {mainTab === 'STOCK LOOKUP' ? (
        <StockLookupPanel />
      ) : mainTab !== 'FACTORS' ? (
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
