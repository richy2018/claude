import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { COLORS, FONT, REGIME_COLORS, REGIME_LABELS } from '../utils/theme.js';

const styles = {
  container: {
    backgroundColor: COLORS.card,
    border: `1px solid ${COLORS.cardBorder}`,
    padding: '16px',
    fontFamily: FONT,
  },
  title: {
    color: COLORS.amber,
    fontSize: '13px',
    fontWeight: 700,
    letterSpacing: '0.05em',
    textTransform: 'uppercase',
    marginBottom: '8px',
  },
  explainer: {
    color: COLORS.yellow,
    fontSize: '11px',
    lineHeight: '1.5',
    marginBottom: '14px',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '12px',
    fontFamily: FONT,
  },
  th: {
    color: COLORS.amberDim,
    textAlign: 'left',
    padding: '4px 8px',
    textTransform: 'uppercase',
    fontSize: '11px',
    letterSpacing: '0.06em',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    fontWeight: 600,
  },
  thRight: {
    color: COLORS.amberDim,
    textAlign: 'right',
    padding: '4px 8px',
    textTransform: 'uppercase',
    fontSize: '11px',
    letterSpacing: '0.06em',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    fontWeight: 600,
  },
  td: {
    padding: '5px 8px',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    color: COLORS.white,
    verticalAlign: 'middle',
  },
  tdRight: {
    padding: '5px 8px',
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    color: COLORS.white,
    textAlign: 'right',
    verticalAlign: 'middle',
  },
  regimeCell: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  colorSquare: {
    display: 'inline-block',
    width: '8px',
    height: '8px',
    flexShrink: 0,
  },
  regimeKey: {
    color: COLORS.amberLight,
    fontWeight: 700,
    marginRight: '4px',
  },
  regimeDesc: {
    color: COLORS.textSecondary,
    fontSize: '11px',
  },
  chartContainer: {
    marginTop: '16px',
    backgroundColor: COLORS.bgDark,
    padding: '8px 4px 4px 4px',
  },
};

function signColor(value, invertPositive = false) {
  if (value === null || value === undefined || isNaN(value)) return COLORS.textSecondary;
  if (invertPositive) {
    return value < 0 ? COLORS.green : value > 0 ? COLORS.red : COLORS.white;
  }
  return value > 0 ? COLORS.green : value < 0 ? COLORS.red : COLORS.white;
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null;
  return (
    <div
      style={{
        backgroundColor: COLORS.cardAlt,
        border: `1px solid ${COLORS.cardBorder}`,
        padding: '6px 10px',
        fontFamily: FONT,
        fontSize: '11px',
        color: COLORS.white,
      }}
    >
      <div style={{ color: COLORS.amberLight, marginBottom: '2px' }}>{label}</div>
      <div>{`FREQ: ${payload[0].value.toFixed(1)}%`}</div>
    </div>
  );
};

export default function RegimeFrequency({ stats }) {
  if (!stats || stats.length === 0) return null;

  const chartData = stats.map((s) => ({
    name: s.regime,
    freq: parseFloat(s.freq),
    color: REGIME_COLORS[s.regime] || COLORS.amberDim,
  }));

  return (
    <div style={styles.container}>
      <div style={styles.title}>
        REGIME FREQUENCY &mdash; How often each regime occurs &amp; what returns look like in it
      </div>

      <div style={styles.explainer}>
        Reading the table: FREQ = how often this regime happens. AVG DUR = how many consecutive days
        it typically lasts. SPX/10Y/DXY = the median daily return for each asset while in this
        regime. Green = positive for you (stocks up or yields down). Red = negative.
      </div>

      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Regime</th>
            <th style={styles.thRight}>Freq</th>
            <th style={styles.thRight}>Avg Dur</th>
            <th style={styles.thRight}>SPX</th>
            <th style={styles.thRight}>10Y</th>
            <th style={styles.thRight}>DXY</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((row) => {
            const freqPct = parseFloat(row.freq).toFixed(1);

            const spxVal = row.spx_median;
            const ratesVal = row.rates_median;
            const dxyVal = row.dxy_median;

            const spxPct =
              spxVal !== null && spxVal !== undefined
                ? parseFloat(spxVal).toFixed(2)
                : null;

            const ratesBp =
              ratesVal !== null && ratesVal !== undefined
                ? parseFloat(ratesVal).toFixed(1)
                : null;

            const dxyDisplay =
              dxyVal !== null && dxyVal !== undefined
                ? parseFloat(dxyVal).toFixed(2)
                : null;

            const regimeColor = REGIME_COLORS[row.regime] || row.color || COLORS.amberDim;
            const description = row.description || REGIME_LABELS[row.regime] || '';
            const shortDesc =
              description.length > 38 ? description.slice(0, 36) + '…' : description;

            return (
              <tr key={row.regime}>
                <td style={styles.td}>
                  <div style={styles.regimeCell}>
                    <span
                      style={{ ...styles.colorSquare, backgroundColor: regimeColor }}
                    />
                    <span style={styles.regimeKey}>{row.regime}</span>
                    <span style={styles.regimeDesc}>{shortDesc}</span>
                  </div>
                </td>
                <td style={styles.tdRight}>{freqPct}%</td>
                <td style={styles.tdRight}>
                  {row.avg_dur !== null && row.avg_dur !== undefined
                    ? `${parseFloat(row.avg_dur).toFixed(1)}d`
                    : '—'}
                </td>
                <td
                  style={{
                    ...styles.tdRight,
                    color: spxPct !== null ? signColor(parseFloat(spxPct)) : COLORS.textSecondary,
                  }}
                >
                  {spxPct !== null ? `${spxPct}%` : '—'}
                </td>
                <td
                  style={{
                    ...styles.tdRight,
                    color:
                      ratesBp !== null
                        ? signColor(parseFloat(ratesBp), true)
                        : COLORS.textSecondary,
                  }}
                >
                  {ratesBp !== null ? `${ratesBp}bp` : '—'}
                </td>
                <td
                  style={{
                    ...styles.tdRight,
                    color:
                      dxyDisplay !== null
                        ? signColor(parseFloat(dxyDisplay))
                        : COLORS.textSecondary,
                  }}
                >
                  {dxyDisplay !== null ? `${dxyDisplay}%` : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div style={styles.chartContainer}>
        <ResponsiveContainer width="100%" height={150}>
          <BarChart
            data={chartData}
            margin={{ top: 4, right: 8, left: -16, bottom: 0 }}
            barCategoryGap="20%"
          >
            <XAxis
              dataKey="name"
              tick={{ fill: COLORS.textSecondary, fontSize: 11, fontFamily: FONT }}
              axisLine={{ stroke: COLORS.cardBorder }}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v) => `${v}%`}
              tick={{ fill: COLORS.textSecondary, fontSize: 10, fontFamily: FONT }}
              axisLine={false}
              tickLine={false}
              width={42}
            />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            />
            <Bar dataKey="freq" radius={[2, 2, 0, 0]}>
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
