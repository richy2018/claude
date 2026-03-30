import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, BarChart, Bar, Cell,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme.js';
import { getStir } from '../utils/api';

// ─── helpers ────────────────────────────────────────────────────────────────

function fmt(v, decimals = 3) {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(decimals);
}

function fmtBp(v) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  return (n > 0 ? '+' : '') + n.toFixed(1) + ' bp';
}

// ─── sub-components ─────────────────────────────────────────────────────────

function TabButton({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: FONT,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.08em',
        padding: '3px 10px',
        background: active ? COLORS.amber : 'transparent',
        color: active ? COLORS.bgDark : COLORS.textSecondary,
        border: `1px solid ${active ? COLORS.amber : COLORS.cardBorder}`,
        cursor: 'pointer',
        marginLeft: 4,
        userSelect: 'none',
      }}
    >
      {label}
    </button>
  );
}

function SummaryBox({ label, value, sub, color }) {
  return (
    <div style={{
      background: COLORS.card,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: '12px 16px',
      minWidth: 140,
      flex: '1 1 140px',
    }}>
      <div style={{
        fontFamily: FONT,
        fontSize: 10,
        color: COLORS.textMuted,
        letterSpacing: '0.1em',
        marginBottom: 6,
        textTransform: 'uppercase',
      }}>
        {label}
      </div>
      <div style={{
        fontFamily: FONT,
        fontSize: 22,
        fontWeight: 700,
        color: color || COLORS.amber,
        lineHeight: 1,
        marginBottom: sub ? 6 : 0,
      }}>
        {value}
      </div>
      {sub && (
        <div style={{
          fontFamily: FONT,
          fontSize: 10,
          color: COLORS.textMuted,
          marginTop: 4,
        }}>
          {sub}
        </div>
      )}
    </div>
  );
}

// ─── custom tooltip ──────────────────────────────────────────────────────────

function PathTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{
      background: COLORS.bgDark,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: '8px 12px',
      fontFamily: FONT,
      fontSize: 11,
    }}>
      <div style={{ color: COLORS.textSecondary, marginBottom: 4 }}>{d.label}</div>
      <div style={{ color: COLORS.amber }}>{fmt(d.rate, 3)}%</div>
    </div>
  );
}

function SpreadTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{
      background: COLORS.bgDark,
      border: `1px solid ${COLORS.cardBorder}`,
      padding: '8px 12px',
      fontFamily: FONT,
      fontSize: 11,
    }}>
      <div style={{ color: COLORS.textSecondary, marginBottom: 4 }}>{d.label}</div>
      <div style={{ color: d.spread_bp >= 0 ? COLORS.green : COLORS.red }}>
        {fmtBp(d.spread_bp)}
      </div>
    </div>
  );
}

// ─── MEETINGS view ───────────────────────────────────────────────────────────

function MeetingsView({ data }) {
  const { current_ffr, terminal, implied_path, meeting_probabilities } = data;

  const frntColor = terminal.frnt_term <= 0 ? COLORS.amber : COLORS.red;
  const term6mColor = terminal.term_6m >= 0 ? COLORS.green : COLORS.red;
  const term12mColor = terminal.term_12m >= 0 ? COLORS.green : COLORS.red;

  const yMin = implied_path && implied_path.length
    ? Math.min(...implied_path.map(d => d.rate)) - 0.1
    : 'auto';
  const yMax = implied_path && implied_path.length
    ? Math.max(...implied_path.map(d => d.rate)) + 0.1
    : 'auto';

  return (
    <div>
      {/* ── Summary boxes ── */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <SummaryBox
          label="TERMINAL"
          value={terminal.terminal_pct}
          sub={terminal.terminal_contract}
          color={COLORS.amber}
        />
        <SummaryBox
          label="FRNT > TERM"
          value={fmtBp(terminal.frnt_term)}
          color={frntColor}
        />
        <SummaryBox
          label="TERM > +6M"
          value={fmtBp(terminal.term_6m)}
          color={term6mColor}
        />
        <SummaryBox
          label="TERM > +12M"
          value={fmtBp(terminal.term_12m)}
          color={term12mColor}
        />
      </div>

      {/* ── Implied path chart ── */}
      <div style={{ marginBottom: 16 }}>
        <div style={{
          fontFamily: FONT,
          fontSize: 12,
          color: COLORS.amber,
          letterSpacing: '0.08em',
          marginBottom: 8,
          textTransform: 'uppercase',
        }}>
          FED FUNDS IMPLIED PATH
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart
            data={implied_path}
            margin={{ top: 8, right: 16, left: -8, bottom: 32 }}
          >
            <XAxis
              dataKey="label"
              tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
              angle={-45}
              textAnchor="end"
              axisLine={{ stroke: COLORS.cardBorder }}
              tickLine={{ stroke: COLORS.cardBorder }}
            />
            <YAxis
              tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
              axisLine={{ stroke: COLORS.cardBorder }}
              tickLine={{ stroke: COLORS.cardBorder }}
              domain={[yMin, yMax]}
              tickFormatter={v => v.toFixed(2)}
              width={48}
            />
            <Tooltip content={<PathTooltip />} />
            <ReferenceLine
              y={current_ffr}
              stroke={COLORS.green}
              strokeDasharray="4 4"
              strokeWidth={1}
            />
            <Line
              type="stepAfter"
              dataKey="rate"
              stroke={COLORS.amber}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ── Decorative progress bar ── */}
      <div style={{
        width: '100%',
        height: 4,
        background: COLORS.cardBorder,
        marginBottom: 14,
        position: 'relative',
      }}>
        <div style={{
          position: 'absolute',
          left: 0,
          top: 0,
          height: '100%',
          width: '90%',
          background: COLORS.amber,
        }} />
      </div>

      {/* ── Meeting probability table ── */}
      <div style={{
        maxHeight: 300,
        overflowY: 'auto',
        border: `1px solid ${COLORS.cardBorder}`,
      }}>
        <table style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontFamily: FONT,
          fontSize: 12,
        }}>
          <thead>
            <tr style={{ position: 'sticky', top: 0, zIndex: 1, background: COLORS.bgDark }}>
              {['MTG', 'RATE', 'POST-MTG', 'HOLD', '-25', '-50', '-75', 'CUTS'].map(col => (
                <th
                  key={col}
                  style={{
                    color: COLORS.textMuted,
                    fontSize: 10,
                    letterSpacing: '0.1em',
                    textAlign: 'right',
                    padding: '6px 10px',
                    fontWeight: 400,
                    borderBottom: `1px solid ${COLORS.cardBorder}`,
                    whiteSpace: 'nowrap',
                    textTransform: 'uppercase',
                  }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(meeting_probabilities || []).map((m, i) => {
              const rowBg = i % 2 === 0 ? COLORS.card : 'transparent';
              const postColor = m.post_mtg < m.rate
                ? COLORS.green
                : m.post_mtg > m.rate
                  ? COLORS.red
                  : COLORS.white;
              const holdColor = m.hold > 80 ? COLORS.amber : COLORS.white;
              const cut25Color = m.cut_25 > 50 ? COLORS.green : COLORS.white;
              const cut50Color = m.cut_50 > 30 ? COLORS.green : COLORS.white;
              const cut75Color = m.cut_75 > 10 ? COLORS.green : COLORS.white;
              const cutsColor = m.cum_cuts > 0.5 ? COLORS.yellow : COLORS.textSecondary;

              const tdStyle = {
                padding: '5px 10px',
                textAlign: 'right',
                borderBottom: `1px solid ${COLORS.cardBorder}`,
                color: COLORS.white,
              };

              return (
                <tr key={i} style={{ background: rowBg }}>
                  <td style={{ ...tdStyle, textAlign: 'left', color: COLORS.textSecondary, whiteSpace: 'nowrap' }}>
                    {m.date_label}&nbsp;
                    <span style={{ color: COLORS.textMuted, fontSize: 10 }}>{m.contract}</span>
                  </td>
                  <td style={tdStyle}>{fmt(m.rate, 3)}</td>
                  <td style={{ ...tdStyle, color: postColor }}>{fmt(m.post_mtg, 3)}</td>
                  <td style={{ ...tdStyle, color: holdColor, fontWeight: m.hold > 80 ? 700 : 400 }}>{m.hold}%</td>
                  <td style={{ ...tdStyle, color: cut25Color }}>{m.cut_25}%</td>
                  <td style={{ ...tdStyle, color: cut50Color }}>{m.cut_50}%</td>
                  <td style={{ ...tdStyle, color: cut75Color }}>{m.cut_75}%</td>
                  <td style={{ ...tdStyle, color: cutsColor }}>{fmt(m.cum_cuts, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── STRIP view ──────────────────────────────────────────────────────────────

function StripView({ strip }) {
  const [rateMode, setRateMode] = useState('MID');

  const rateField = rateMode === 'BID' ? 'bid' : rateMode === 'ASK' ? 'ask' : 'mid';

  const tdStyle = {
    padding: '5px 10px',
    textAlign: 'right',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    fontFamily: FONT,
    fontSize: 12,
  };

  return (
    <div>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 12,
        flexWrap: 'wrap',
        gap: 8,
      }}>
        <div style={{
          fontFamily: FONT,
          fontSize: 12,
          color: COLORS.amber,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        }}>
          SOFR STRIP — USD SOFR Swap Rates
        </div>
        <div style={{ display: 'flex', gap: 0 }}>
          {['BID', 'MID', 'ASK'].map(m => (
            <button
              key={m}
              onClick={() => setRateMode(m)}
              style={{
                fontFamily: FONT,
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.08em',
                padding: '3px 10px',
                background: rateMode === m ? COLORS.amber : 'transparent',
                color: rateMode === m ? COLORS.bgDark : COLORS.textSecondary,
                border: `1px solid ${COLORS.cardBorder}`,
                borderLeft: m === 'BID' ? `1px solid ${COLORS.cardBorder}` : 'none',
                cursor: 'pointer',
                userSelect: 'none',
              }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div style={{ border: `1px solid ${COLORS.cardBorder}`, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: FONT, fontSize: 12 }}>
          <thead>
            <tr style={{ background: COLORS.bgDark }}>
              {['TENOR', 'RATE', 'BID', 'ASK', 'SPREAD', 'DAYCOUNT'].map(col => (
                <th
                  key={col}
                  style={{
                    ...tdStyle,
                    color: COLORS.textMuted,
                    fontSize: 10,
                    fontWeight: 400,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    borderBottom: `1px solid ${COLORS.cardBorder}`,
                    textAlign: col === 'TENOR' ? 'left' : 'right',
                  }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(strip || []).map((row, i) => {
              const spreadBp = row.ask != null && row.bid != null
                ? ((row.ask - row.bid) * 100).toFixed(1)
                : '—';
              return (
                <tr key={i} style={{ background: i % 2 === 0 ? COLORS.card : 'transparent' }}>
                  <td style={{ ...tdStyle, textAlign: 'left', color: COLORS.white, fontWeight: 600 }}>{row.label}</td>
                  <td style={{ ...tdStyle, color: COLORS.amber, fontWeight: 700 }}>{fmt(row[rateField], 3)}%</td>
                  <td style={{ ...tdStyle, color: COLORS.textSecondary }}>{fmt(row.bid, 3)}</td>
                  <td style={{ ...tdStyle, color: COLORS.textSecondary }}>{fmt(row.ask, 3)}</td>
                  <td style={{ ...tdStyle, color: COLORS.textMuted }}>{spreadBp} bp</td>
                  <td style={{ ...tdStyle, color: COLORS.textMuted }}>{row.daycount || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── SPREADS view ────────────────────────────────────────────────────────────

function SpreadsView({ spreads }) {
  const tdStyle = {
    padding: '5px 10px',
    textAlign: 'right',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    fontFamily: FONT,
    fontSize: 12,
  };

  return (
    <div>
      <div style={{
        fontFamily: FONT,
        fontSize: 12,
        color: COLORS.amber,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        marginBottom: 12,
      }}>
        KEY RATE SPREADS
      </div>

      <div style={{ border: `1px solid ${COLORS.cardBorder}`, marginBottom: 16, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: FONT, fontSize: 12 }}>
          <thead>
            <tr style={{ background: COLORS.bgDark }}>
              {['SPREAD', 'SHORT RATE', 'LONG RATE', 'SPREAD (BP)'].map(col => (
                <th
                  key={col}
                  style={{
                    ...tdStyle,
                    color: COLORS.textMuted,
                    fontSize: 10,
                    fontWeight: 400,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    borderBottom: `1px solid ${COLORS.cardBorder}`,
                    textAlign: col === 'SPREAD' ? 'left' : 'right',
                  }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(spreads || []).map((row, i) => {
              const bpColor = row.spread_bp >= 0 ? COLORS.green : COLORS.red;
              return (
                <tr key={i} style={{ background: i % 2 === 0 ? COLORS.card : 'transparent' }}>
                  <td style={{ ...tdStyle, textAlign: 'left', color: COLORS.white }}>{row.label}</td>
                  <td style={{ ...tdStyle, color: COLORS.textSecondary }}>{fmt(row.short_rate, 3)}%</td>
                  <td style={{ ...tdStyle, color: COLORS.textSecondary }}>{fmt(row.long_rate, 3)}%</td>
                  <td style={{ ...tdStyle, color: bpColor, fontWeight: 700 }}>{fmtBp(row.spread_bp)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ResponsiveContainer width="100%" height={180}>
        <BarChart
          data={spreads || []}
          margin={{ top: 8, right: 16, left: -8, bottom: 8 }}
        >
          <XAxis
            dataKey="label"
            tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={{ stroke: COLORS.cardBorder }}
          />
          <YAxis
            tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }}
            axisLine={{ stroke: COLORS.cardBorder }}
            tickLine={{ stroke: COLORS.cardBorder }}
            tickFormatter={v => v.toFixed(1)}
            width={40}
          />
          <Tooltip content={<SpreadTooltip />} />
          <ReferenceLine y={0} stroke={COLORS.cardBorder} />
          <Bar dataKey="spread_bp" isAnimationActive={false}>
            {(spreads || []).map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.spread_bp >= 0 ? COLORS.green : COLORS.red}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── CB LVL view ─────────────────────────────────────────────────────────────

const CB_DATA = [
  { name: 'Federal Reserve', code: 'FED', rate: '3.625%', lastChange: 'Mar 2026  -25bp' },
  { name: 'European Central Bank', code: 'ECB', rate: '2.750%', lastChange: 'Jan 2026  -25bp' },
  { name: 'Bank of England', code: 'BOE', rate: '4.500%', lastChange: 'Feb 2026  hold' },
  { name: 'Bank of Japan', code: 'BOJ', rate: '0.500%', lastChange: 'Jan 2026  +25bp' },
];

function CbLvlView() {
  const tdStyle = {
    padding: '7px 12px',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    fontFamily: FONT,
    fontSize: 12,
    color: COLORS.textSecondary,
  };

  return (
    <div>
      <div style={{
        fontFamily: FONT,
        fontSize: 12,
        color: COLORS.amber,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        marginBottom: 8,
      }}>
        CENTRAL BANK RATE LEVELS
      </div>
      <div style={{
        fontFamily: FONT,
        fontSize: 10,
        color: COLORS.textMuted,
        marginBottom: 14,
        letterSpacing: '0.05em',
      }}>
        PLACEHOLDER — LIVE DATA COMING SOON
      </div>

      <div style={{ border: `1px solid ${COLORS.cardBorder}` }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: FONT, fontSize: 12 }}>
          <thead>
            <tr style={{ background: COLORS.bgDark }}>
              {['CENTRAL BANK', 'RATE', 'LAST CHANGE'].map(col => (
                <th
                  key={col}
                  style={{
                    ...tdStyle,
                    color: COLORS.textMuted,
                    fontSize: 10,
                    fontWeight: 400,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    borderBottom: `1px solid ${COLORS.cardBorder}`,
                    textAlign: col === 'CENTRAL BANK' ? 'left' : 'right',
                  }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CB_DATA.map((row, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? COLORS.card : 'transparent' }}>
                <td style={{ ...tdStyle, textAlign: 'left' }}>
                  {row.name}
                  <span style={{ color: COLORS.textMuted, marginLeft: 8, fontSize: 10 }}>{row.code}</span>
                </td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>{row.rate}</td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>{row.lastChange}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function STIRPanel() {
  const [activeTab, setActiveTab] = useState('MEETINGS');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const TABS = ['MEETINGS', 'STRIP', 'SPREADS', 'CB LVL'];

  useEffect(() => {
    setLoading(true);
    getStir()
      .then(d => {
        setData(d);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message || 'Failed to load STIR data');
        setLoading(false);
      });
  }, []);

  return (
    <div style={{
      background: COLORS.bg,
      border: `1px solid ${COLORS.cardBorder}`,
      fontFamily: FONT,
      padding: 0,
      width: '100%',
      boxSizing: 'border-box',
    }}>
      {/* ── Panel header ── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 16px',
        borderBottom: `1px solid ${COLORS.cardBorder}`,
        background: COLORS.bgDark,
        flexWrap: 'wrap',
        gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{
            fontFamily: FONT,
            fontSize: 16,
            fontWeight: 700,
            color: COLORS.amber,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
          }}>
            US STIR
          </span>
          {data && (
            <span style={{
              fontFamily: FONT,
              fontSize: 13,
              color: COLORS.white,
              letterSpacing: '0.05em',
            }}>
              FFR {data.current_ffr}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          {TABS.map(tab => (
            <TabButton
              key={tab}
              label={tab}
              active={activeTab === tab}
              onClick={() => setActiveTab(tab)}
            />
          ))}
        </div>
      </div>

      {/* ── Content area ── */}
      <div style={{ padding: '16px' }}>
        {loading && (
          <div style={{
            fontFamily: FONT,
            fontSize: 12,
            color: COLORS.textMuted,
            textAlign: 'center',
            padding: '40px 0',
            letterSpacing: '0.1em',
          }}>
            LOADING STIR DATA...
          </div>
        )}

        {error && !loading && (
          <div style={{
            fontFamily: FONT,
            fontSize: 12,
            color: COLORS.red,
            textAlign: 'center',
            padding: '40px 0',
            letterSpacing: '0.08em',
          }}>
            ERROR: {error}
          </div>
        )}

        {!loading && !error && data && (
          <>
            {activeTab === 'MEETINGS' && <MeetingsView data={data} />}
            {activeTab === 'STRIP' && <StripView strip={data.strip} />}
            {activeTab === 'SPREADS' && <SpreadsView spreads={data.spreads} />}
            {activeTab === 'CB LVL' && <CbLvlView />}
          </>
        )}
      </div>
    </div>
  );
}
