import React from 'react';

/**
 * Signature view — cross-asset positioning heatmap.
 * Rows grouped by class (indices / FX / rates / commodities); cell colour =
 * primary-cohort COT index (blue ≈0 net-short extreme → neutral → red ≈100
 * net-long extreme); shows value + a 4-week delta and a recent sparkline.
 * Cells >90 / <10 are flagged. Click a row → detail chart.
 * This is the "where are the crowded trades right now" view.
 */

const PAL = { bg: '#070708', line: '#26262c', txt: '#e6e6e8', mut: '#6f6f78', dim: '#48484f', red: '#f0463a', blue: '#5b9dff' };
const MONO = "'IBM Plex Mono',ui-monospace,monospace";

// blue (0, net-short extreme) → neutral → red (100, net-long extreme)
function cellColor(v) {
  if (v == null) return '#0d0d0f';
  const mid = [26, 26, 30];      // #1a1a1e
  const lo = [91, 157, 255];     // blue
  const hi = [240, 70, 58];      // red
  let a, b, t;
  if (v <= 50) { a = lo; b = mid; t = v / 50; } else { a = mid; b = hi; t = (v - 50) / 50; }
  const c = a.map((x, i) => Math.round(x + (b[i] - x) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function Spark({ vals }) {
  const pts = (vals || []).filter((v) => v != null);
  if (pts.length < 2) return <svg width="56" height="16" />;
  const min = Math.min(...pts), max = Math.max(...pts), rng = max - min || 1;
  const W = 56, H = 16;
  const d = pts.map((v, i) => `${(i / (pts.length - 1)) * W},${H - ((v - min) / rng) * H}`).join(' ');
  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <polyline points={d} fill="none" stroke={PAL.mut} strokeWidth="1" />
    </svg>
  );
}

const delta = (d) => (d == null ? '—' : (d >= 0 ? '+' : '') + d.toFixed(1));

export default function COTHeatmap({ data, onSelect, selected }) {
  if (!data) return null;
  return (
    <div style={S.wrap}>
      <div style={S.head}>
        <div style={S.h1}>Cross-Asset Positioning <span style={S.tk}>/ COT Heatmap</span></div>
        <div style={S.sub}>
          PRIMARY SPECULATIVE COHORT · {data.lookback}-WEEK COT INDEX (0–100) ·
          BLUE = NET-SHORT EXTREME · RED = NET-LONG EXTREME · ★ &gt;90 / &lt;10 FLAGGED
        </div>
      </div>

      <div style={S.legendRow}>
        <span style={{ color: PAL.blue }}>◧ 0 net-short</span>
        <span style={{ color: PAL.mut }}>50 neutral</span>
        <span style={{ color: PAL.red }}>100 net-long ◧</span>
      </div>

      {(data.groups || []).map((g) => (
        <div key={g.class} style={{ marginTop: 14 }}>
          <div style={S.groupLabel}>{g.class_label}</div>
          <div style={S.grid}>
            {g.assets.map((a) => {
              const isSel = selected === a.symbol;
              const flagged = a.flag === 'high' || a.flag === 'low';
              return (
                <div key={a.symbol} onClick={() => onSelect && onSelect(a.symbol)}
                  title={a.value == null ? `${a.symbol}: no data / warming up` : `${a.symbol} ${a.cohort_label}: COT idx ${a.value?.toFixed(1)}  (net ${a.net?.toLocaleString?.() ?? a.net})  as of ${a.date}`}
                  style={{
                    ...S.cell, background: cellColor(a.value),
                    border: isSel ? `1px solid ${PAL.txt}` : flagged ? `1px solid ${a.flag === 'high' ? PAL.red : PAL.blue}` : `1px solid ${PAL.line}`,
                    cursor: a.value == null ? 'default' : 'pointer',
                  }}>
                  <div style={S.cellTop}>
                    <span style={S.sym}>{a.symbol}</span>
                    {flagged && <span style={{ color: a.flag === 'high' ? '#fff' : '#fff', fontSize: 9 }}>{a.flag === 'high' ? '★HI' : '★LO'}</span>}
                  </div>
                  <div style={S.val}>{a.value == null ? 'n/a' : a.value.toFixed(0)}</div>
                  <div style={S.cellBot}>
                    <span style={{ color: (a.chg_4w ?? 0) >= 0 ? '#cfe6ff' : '#ffd2cd', fontSize: 9.5 }}>
                      4w {delta(a.chg_4w)}
                    </span>
                    <Spark vals={a.spark} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {data.disclaimer && <div style={S.disc}>{data.disclaimer}</div>}
    </div>
  );
}

const S = {
  wrap: { background: PAL.bg, color: PAL.txt, fontFamily: MONO, padding: 20, borderRadius: 6, border: `1px solid ${PAL.line}` },
  head: { borderBottom: `1px solid ${PAL.line}`, paddingBottom: 12 },
  h1: { fontFamily: "'Instrument Serif',serif", fontWeight: 400, fontSize: 32, letterSpacing: 0.3 },
  tk: { color: PAL.mut, fontStyle: 'italic' },
  sub: { color: PAL.mut, fontSize: 10.5, marginTop: 6, letterSpacing: 0.4 },
  legendRow: { display: 'flex', gap: 18, fontSize: 10, marginTop: 10, color: PAL.mut },
  groupLabel: { fontSize: 11, color: '#8a8a92', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 6 },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))', gap: 6 },
  cell: { borderRadius: 4, padding: '7px 9px', minHeight: 64, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' },
  cellTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  sym: { fontSize: 12, fontWeight: 600, letterSpacing: 0.5 },
  val: { fontSize: 22, fontWeight: 600, lineHeight: 1, fontFamily: "'Instrument Serif',serif" },
  cellBot: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 6 },
  disc: { color: PAL.dim, fontSize: 9.5, marginTop: 16, fontStyle: 'italic', borderTop: `1px solid ${PAL.line}`, paddingTop: 8 },
};
