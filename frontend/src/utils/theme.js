/**
 * Terminal/Bloomberg-style dark theme constants.
 * Phase 9: Colors aligned to exact design spec.
 */
export const COLORS = {
  // Backgrounds
  bg: '#0a0a0a',
  bgDark: '#050505',
  card: '#0d0d0d',
  cardAlt: '#111111',
  cardBorder: '#333333',
  cardBorderHover: '#444444',

  // Primary amber/orange (headers, labels, titles, accent)
  amber: '#ffaa00',
  amberLight: '#ffcc00',
  amberDim: '#8a6600',

  // Data values
  green: '#00ff88',
  greenDim: '#00802a',
  red: '#ff4444',
  redDim: '#b2102f',

  // Chart/accent
  cyan: '#00e5ff',
  blue: '#448aff',
  purple: '#b388ff',
  pink: '#ff80ab',
  orange: '#ff9100',

  // Factor decomposition colors (Bloomberg-consistent)
  factorMkt: '#f59e0b',   // amber/orange for Market
  factorSec: '#22d3ee',   // cyan for Sector
  factorFund: '#22c55e',  // green for Fund/Alpha (positive)
  factorFundNeg: '#ef4444', // red for Fund/Alpha (negative)

  // Text hierarchy
  white: '#cccccc',         // secondary text / data values
  textPrimary: '#ffaa00',   // amber - headers, labels
  textSecondary: '#cccccc', // light gray - data values
  textMuted: '#888888',     // dim gray - explanatory text
  textDim: '#555555',       // very dim

  // Callout / explanatory
  yellow: '#ffcc00',
};

export const FONT = "'JetBrains Mono', 'Fira Code', 'IBM Plex Mono', 'Courier New', monospace";

export const REGIME_COLORS = {
  R1: '#00cc44',  // Stocks Up / Rates Up / Dollar Up — green
  R2: '#008833',  // Stocks Up / Rates Up / Dollar Down — dark green
  R3: '#00cccc',  // Stocks Up / Rates Down / Dollar Up — cyan
  R4: '#4488ff',  // Stocks Up / Rates Down / Dollar Down — light blue
  R5: '#ff4444',  // Stocks Down / Rates Up / Dollar Up — red
  R6: '#ff8800',  // Stocks Down / Rates Up / Dollar Down — orange
  R7: '#8844cc',  // Stocks Down / Rates Down / Dollar Up — purple
  R8: '#cc44aa',  // Stocks Down / Rates Down / Dollar Down — pink/magenta
};

export const REGIME_LABELS = {
  R1: 'Stocks Up / Rates Up / Dollar Up',
  R2: 'Stocks Up / Rates Up / Dollar Down',
  R3: 'Stocks Up / Rates Down / Dollar Up',
  R4: 'Stocks Up / Rates Down / Dollar Down',
  R5: 'Stocks Down / Rates Up / Dollar Up',
  R6: 'Stocks Down / Rates Up / Dollar Down',
  R7: 'Stocks Down / Rates Down / Dollar Up',
  R8: 'Stocks Down / Rates Down / Dollar Down',
};
