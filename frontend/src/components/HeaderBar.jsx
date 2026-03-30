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
    const id = setInterval(() => setNow(formatTimestamp(new Date())), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      height: 48, padding: '0 20px',
      backgroundColor: COLORS.bg, borderBottom: `1px solid ${COLORS.cardBorder}`,
      fontFamily: FONT, flexShrink: 0,
    }}>
      {/* Left: branding */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ color: COLORS.amber, fontWeight: 'bold', fontSize: 15, letterSpacing: '0.08em' }}>
          CFR
        </span>
        <span style={{ color: COLORS.textMuted, fontSize: 12 }}>|</span>
        <span style={{ color: COLORS.white, fontSize: 13, letterSpacing: '0.06em' }}>
          RATES REGIME DASHBOARD
        </span>
        <span style={{ color: COLORS.textMuted, fontSize: 11 }}>v1.0</span>
      </div>

      {/* Right: controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ color: COLORS.amberDim, fontSize: 11, letterSpacing: '0.05em' }}>
          US 1s 2s 5s 10s 30s
        </span>
        <span style={{ color: COLORS.textMuted, fontSize: 10 }}>|</span>
        <span style={{ color: COLORS.amberDim, fontSize: 11, letterSpacing: '0.05em' }}>
          NOM + REAL + INF SWAPS
        </span>
        <span style={{ color: COLORS.textMuted, fontSize: 10 }}>|</span>
        <span style={{ color: COLORS.white, fontSize: 12, letterSpacing: '0.04em' }}>
          {now}
        </span>

        {/* Last updated */}
        {lastRefresh && (
          <span style={{ color: COLORS.textMuted, fontSize: 10 }}>
            Updated: {new Date(lastRefresh).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}

        {/* Refresh button */}
        <button
          onClick={!isLoading ? onRefresh : undefined}
          disabled={isLoading}
          style={{
            fontFamily: FONT, fontSize: 11, letterSpacing: '0.08em', fontWeight: 'bold',
            padding: '4px 12px',
            backgroundColor: isLoading ? 'transparent' : 'transparent',
            color: isLoading ? COLORS.green : COLORS.amber,
            border: `1px solid ${isLoading ? COLORS.green : COLORS.amber}`,
            cursor: isLoading ? 'not-allowed' : 'pointer',
          }}
        >
          {isLoading ? 'RUNNING...' : 'REFRESH'}
        </button>

        {/* Agentic Analysis */}
        <button
          disabled
          style={{
            fontFamily: FONT, fontSize: 11, letterSpacing: '0.08em', fontWeight: 'bold',
            padding: '4px 12px',
            backgroundColor: 'transparent',
            color: COLORS.amberLight,
            border: `1px solid ${COLORS.greenDim}`,
            cursor: 'default', opacity: 0.7,
          }}
        >
          AGENTIC ANALYSIS
        </button>

        {/* Running indicator dot */}
        {isLoading && (
          <div style={{
            width: 8, height: 8, backgroundColor: COLORS.green,
            animation: 'pulse 1s infinite',
          }} />
        )}
      </div>

      {/* Inline keyframe for pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
