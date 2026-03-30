import React from 'react';
import { COLORS, FONT, REGIME_COLORS } from '../utils/theme';

export default function CurrentRegimeBanner({
  regime,
  description,
  color,
  spxMetric,
  ratesMetric,
  dxyMetric,
  linkage,
  linkageLabel,
}) {
  const formatMetric = (val) => {
    if (val == null) return '—';
    const num = parseFloat(val);
    return (num >= 0 ? '+' : '') + num.toFixed(2);
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '10px 16px',
        backgroundColor: COLORS.card,
        borderLeft: `4px solid ${color || COLORS.amber}`,
        border: `1px solid ${color || COLORS.amber}33`,
        fontFamily: FONT,
        marginBottom: 8,
      }}
    >
      <div
        style={{
          width: 14,
          height: 14,
          backgroundColor: color || COLORS.amber,
          flexShrink: 0,
        }}
      />
      <span style={{ color: color || COLORS.amber, fontSize: 13, fontWeight: 'bold' }}>
        {description || 'Unknown Regime'}
      </span>
      <span style={{ color: COLORS.white, fontSize: 12 }}>
        SPX: <span style={{ color: parseFloat(spxMetric) >= 0 ? COLORS.green : COLORS.red }}>
          {formatMetric(spxMetric)}
        </span>
      </span>
      <span style={{ color: COLORS.white, fontSize: 12 }}>
        10Y: <span style={{ color: parseFloat(ratesMetric) >= 0 ? COLORS.red : COLORS.green }}>
          {formatMetric(ratesMetric)}
        </span>
      </span>
      <span style={{ color: COLORS.white, fontSize: 12 }}>
        DXY: <span style={{ color: parseFloat(dxyMetric) >= 0 ? COLORS.amber : COLORS.cyan }}>
          {formatMetric(dxyMetric)}
        </span>
      </span>
      <span style={{ color: COLORS.textMuted, fontSize: 11 }}>|</span>
      <span
        style={{
          color: linkageLabel === 'STRONGLY LINKED' ? COLORS.amber :
                 linkageLabel === 'MODERATE' ? COLORS.yellow : COLORS.green,
          fontSize: 12,
          fontWeight: 'bold',
          letterSpacing: 1,
        }}
      >
        {linkageLabel} ({linkage != null ? Math.round(linkage) + '%' : '—'})
      </span>
    </div>
  );
}
