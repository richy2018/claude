import React, { useState, useEffect } from 'react';
import { COLORS, FONT } from '../utils/theme.js';

function formatTimestamp(date) {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

export default function HeaderBar({ onRefresh, isLoading, lastRefresh }) {
  const [now, setNow] = useState(() => formatTimestamp(new Date()));

  useEffect(() => {
    const id = setInterval(() => {
      setNow(formatTimestamp(new Date()));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const containerStyle = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    height: '48px',
    padding: '0 20px',
    backgroundColor: COLORS.bg,
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    fontFamily: FONT,
    flexShrink: 0,
    boxSizing: 'border-box',
  };

  const leftStyle = {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  };

  const titleStyle = {
    color: COLORS.amber,
    fontWeight: 'bold',
    fontSize: '15px',
    letterSpacing: '0.08em',
  };

  const subtitleStyle = {
    color: COLORS.white,
    fontSize: '13px',
    letterSpacing: '0.06em',
  };

  const versionStyle = {
    color: COLORS.textMuted,
    fontSize: '11px',
    letterSpacing: '0.04em',
  };

  const rightStyle = {
    display: 'flex',
    alignItems: 'center',
    gap: '20px',
  };

  const metaTextStyle = {
    color: COLORS.amberDim,
    fontSize: '11px',
    letterSpacing: '0.05em',
    whiteSpace: 'nowrap',
  };

  const timestampStyle = {
    color: COLORS.white,
    fontSize: '12px',
    letterSpacing: '0.05em',
    whiteSpace: 'nowrap',
  };

  const refreshButtonStyle = {
    fontFamily: FONT,
    fontSize: '11px',
    letterSpacing: '0.08em',
    fontWeight: 'bold',
    padding: '4px 10px',
    backgroundColor: 'transparent',
    color: isLoading ? COLORS.green : COLORS.amber,
    border: `1px solid ${isLoading ? COLORS.green : COLORS.amber}`,
    cursor: isLoading ? 'not-allowed' : 'pointer',
    outline: 'none',
    whiteSpace: 'nowrap',
    transition: 'opacity 0.15s',
  };

  const agentButtonStyle = {
    fontFamily: FONT,
    fontSize: '11px',
    letterSpacing: '0.08em',
    fontWeight: 'bold',
    padding: '4px 10px',
    backgroundColor: 'transparent',
    color: COLORS.amberLight,
    border: `1px solid ${COLORS.greenDim}`,
    cursor: 'default',
    outline: 'none',
    whiteSpace: 'nowrap',
    opacity: 0.7,
  };

  const dividerStyle = {
    color: COLORS.textMuted,
    fontSize: '12px',
    userSelect: 'none',
  };

  return (
    <div style={containerStyle}>
      {/* Left: branding */}
      <div style={leftStyle}>
        <span style={titleStyle}>CFR</span>
        <span style={dividerStyle}>|</span>
        <span style={subtitleStyle}>RATES REGIME DASHBOARD</span>
        <span style={versionStyle}>v1.0</span>
      </div>

      {/* Right: controls */}
      <div style={rightStyle}>
        <span style={metaTextStyle}>US 1s 2s 5s 10s 30s</span>
        <span style={dividerStyle}>·</span>
        <span style={metaTextStyle}>NOM + REAL + INF SWAPS</span>
        <span style={dividerStyle}>·</span>
        <span style={timestampStyle}>{now}</span>
        <button
          style={refreshButtonStyle}
          onClick={!isLoading ? onRefresh : undefined}
          disabled={isLoading}
        >
          {isLoading ? 'RUNNING...' : 'REFRESH'}
        </button>
        <button style={agentButtonStyle} disabled>
          AGENTIC ANALYSIS
        </button>
      </div>
    </div>
  );
}
