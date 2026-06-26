import React, { useEffect, useMemo, useRef, useState } from 'react';

/**
 * Per-asset COT detail chart — a faithful React/canvas port of
 * backend/data/cot_nq_chart.html, preserving the terminal aesthetic
 * (Instrument Serif title, IBM Plex Mono, black ground, blue/red/yellow
 * cohorts). Generalised from NQ-legacy to any symbol / report type.
 *
 *  - Top panel: diverging net-position bars per cohort, zero-centred.
 *  - Bottom panel: COT-index lines, shaded >90 / <10 bands, dashed 50.
 *  - 3Y / 5Y / 10Y / MAX window + scrubber; legend toggles per cohort.
 *  - Report-type toggle (legacy 3-way <-> TFF/disagg split) handled by parent.
 *  - Hover crosshair + tooltip across both panels.
 *  - Price overlay is pluggable + OFF by default (licensed-data guardrail):
 *    the toggle renders but is disabled until a licensed feed is wired.
 */

const PAL = {
  bg: '#070708', line: '#26262c', txt: '#e6e6e8', mut: '#6f6f78', dim: '#48484f',
  red: '#f0463a', blue: '#5b9dff',
};
const WINDOWS = [
  { label: '3Y', w: 156 }, { label: '5Y', w: 260 },
  { label: '10Y', w: 520 }, { label: 'MAX', w: 0 },
];

// Load the reference fonts once (Instrument Serif + IBM Plex Mono).
function useChartFonts() {
  useEffect(() => {
    const id = 'cot-chart-fonts';
    if (document.getElementById(id)) return;
    const l = document.createElement('link');
    l.id = id;
    l.rel = 'stylesheet';
    l.href = 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Serif:ital@0;1&display=swap';
    document.head.appendChild(l);
  }, []);
}

const fmt = (n) => (n == null ? '—' : (n >= 0 ? '+' : '') + n.toLocaleString('en-US'));

export default function COTDetailChart({ data, reportType, onReportType }) {
  useChartFonts();
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const [winLen, setWinLen] = useState(156);
  const [start, setStart] = useState(0);
  const [hoverX, setHoverX] = useState(null);
  const [enabled, setEnabled] = useState({});
  const [tip, setTip] = useState(null);
  const [logScale, setLogScale] = useState(false);

  const cohorts = useMemo(() => (data?.cohorts_meta || []), [data]);
  const series = data?.series || { cohorts: {}, dates: [] };

  // Build the aligned DATA array: one row per date with each cohort's net + idx.
  const DATA = useMemo(() => {
    const maps = {};
    cohorts.forEach((c) => {
      maps[c.key] = new Map((series.cohorts[c.key] || []).map((r) => [r.date, r]));
    });
    return (series.dates || []).map((d) => {
      const row = { d };
      cohorts.forEach((c) => {
        const r = maps[c.key].get(d);
        row[c.key] = r ? r.net : null;
        row[c.key + '_idx'] = r ? r.cot_index : null;
      });
      return row;
    });
  }, [cohorts, series]);

  // default all cohorts on when the cohort set changes
  useEffect(() => {
    const init = {};
    cohorts.forEach((c) => { init[c.key] = true; });
    setEnabled(init);
  }, [cohorts]);

  // reset window when the dataset changes
  useEffect(() => { setStart(Math.max(0, DATA.length - winLen)); }, [DATA.length]); // eslint-disable-line

  const view = () => {
    const len = winLen === 0 ? DATA.length : Math.min(winLen, DATA.length);
    const s = winLen === 0 ? 0 : Math.min(start, Math.max(0, DATA.length - len));
    return { s, e: s + len, len };
  };

  // ── draw ────────────────────────────────────────────────────────────────
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || DATA.length === 0) return;
    const ctx = cv.getContext('2d');
    const DPR = window.devicePixelRatio || 1;
    const CSSW = wrapRef.current.clientWidth;
    const CSSH = 600;
    cv.width = CSSW * DPR; cv.height = CSSH * DPR;
    cv.style.width = CSSW + 'px'; cv.style.height = CSSH + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, CSSW, CSSH);

    const { s, e, len } = view();
    const slice = DATA.slice(s, e);
    const L = 56, R = 18, W = CSSW - L - R;
    const t0 = 8, t1 = 330, b0 = 372, b1 = 560;
    const zeroY = (t0 + t1) / 2;
    const active = cohorts.filter((c) => enabled[c.key]);

    let maxAbs = 1;
    slice.forEach((d) => active.forEach((c) => {
      if (d[c.key] != null) maxAbs = Math.max(maxAbs, Math.abs(d[c.key]));
    }));
    maxAbs = Math.ceil(maxAbs / 25000) * 25000;
    const barH = (t1 - t0) / 2 - 6;
    const yNet = (v) => zeroY - (v / maxAbs) * barH;
    const yIdx = (v) => b1 - (v / 100) * (b1 - b0);
    const slot = W / len;
    const xAt = (i) => L + (i + 0.5) * slot;

    ctx.font = '10px "IBM Plex Mono",monospace';
    ctx.textBaseline = 'middle';

    // grid — bars panel
    for (let g = -maxAbs; g <= maxAbs; g += maxAbs / 2) {
      const y = yNet(g);
      ctx.globalAlpha = g === 0 ? 1 : 0.6;
      ctx.strokeStyle = g === 0 ? '#33333a' : '#141418';
      ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(L + W, y); ctx.stroke();
      ctx.globalAlpha = 1; ctx.textAlign = 'right'; ctx.fillStyle = '#5a5a62';
      ctx.fillText((g / 1000) + 'k', L - 8, y);
    }
    ctx.fillStyle = '#8a8a92'; ctx.textAlign = 'left';
    ctx.fillText('NET POSITION (contracts)', L + 2, t0 + 8);

    // bars
    const sub = Math.max(0.6, (slot / Math.max(active.length, 1)) * 0.74);
    slice.forEach((d, i) => {
      const cx = L + i * slot + slot / 2;
      active.forEach((c, ci) => {
        const v = d[c.key];
        if (v == null) return;
        const y = yNet(v);
        ctx.fillStyle = c.color;
        const bx = cx + (ci - (active.length - 1) / 2) * sub;
        ctx.fillRect(bx - sub / 2, Math.min(y, zeroY), sub * 0.92, Math.abs(y - zeroY) || 0.5);
      });
    });

    // index panel — extreme bands
    ctx.fillStyle = 'rgba(240,70,58,0.07)';
    ctx.fillRect(L, yIdx(100), W, yIdx(90) - yIdx(100));
    ctx.fillStyle = 'rgba(91,157,255,0.07)';
    ctx.fillRect(L, yIdx(10), W, yIdx(0) - yIdx(10));
    [0, 50, 100].forEach((g) => {
      const y = yIdx(g);
      ctx.globalAlpha = g === 50 ? 0.8 : 1;
      ctx.setLineDash(g === 50 ? [2, 3] : []);
      ctx.strokeStyle = g === 50 ? '#26262c' : '#141418';
      ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(L + W, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#5a5a62'; ctx.textAlign = 'right'; ctx.fillText(g, L - 8, y);
    });
    ctx.globalAlpha = 1; ctx.fillStyle = '#8a8a92'; ctx.textAlign = 'left';
    ctx.fillText('COT INDEX  (' + (data?.lookback || 156) + 'w stochastic, 0–100)', L + 2, b0 - 2);

    // index lines
    active.forEach((c) => {
      ctx.strokeStyle = c.color; ctx.lineWidth = 1.4; ctx.beginPath();
      let started = false;
      slice.forEach((d, i) => {
        const v = d[c.key + '_idx'];
        if (v == null) { started = false; return; }
        const x = xAt(i), y = yIdx(v);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      });
      ctx.stroke(); ctx.lineWidth = 1;
    });

    // x axis year ticks
    ctx.fillStyle = '#5a5a62'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    let lastYr = null;
    slice.forEach((d, i) => {
      const y = d.d.slice(0, 4);
      if (y !== lastYr) {
        lastYr = y;
        const x = xAt(i);
        ctx.strokeStyle = '#141418';
        ctx.beginPath(); ctx.moveTo(x, t0); ctx.lineTo(x, b1); ctx.stroke();
        ctx.fillText(y, x, b1 + 6);
      }
    });
    ctx.textBaseline = 'middle';

    // hover crosshair
    let hi = null;
    if (hoverX != null) {
      const i = Math.floor((hoverX - L) / slot);
      if (i >= 0 && i < slice.length) {
        hi = i;
        const x = xAt(i);
        ctx.strokeStyle = 'rgba(255,255,255,0.22)'; ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(x, t0); ctx.lineTo(x, b1); ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    if (hi != null) {
      const d = slice[hi];
      setTip({
        x: xAt(hi),
        d: d.d,
        rows: active.map((c) => ({
          label: c.label, color: c.color, net: d[c.key], idx: d[c.key + '_idx'],
        })),
      });
    } else {
      setTip(null);
    }
  }, [DATA, cohorts, enabled, winLen, start, hoverX, data]);

  if (!data) return null;
  const { s, e } = view();
  const rangeLabel = DATA.length ? `${DATA[s]?.d}  →  ${DATA[Math.min(e, DATA.length) - 1]?.d}` : '';
  const last = DATA[DATA.length - 1] || {};

  return (
    <div ref={wrapRef} style={S.wrap}>
      {/* header */}
      <div style={S.top}>
        <div>
          <div style={S.h1}>{data.class_label} <span style={S.tk}>/ {data.symbol}</span></div>
          <div style={S.sub}>
            CFTC {reportType === 'legacy_fut' ? 'LEGACY' : reportType.toUpperCase()} COMMITMENT OF TRADERS ·
            FUTURES-ONLY · WEEKLY · {data.n_weeks} OBS · {data.contract_name || '—'}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          {/* report-type toggle */}
          <div style={S.seg}>
            {(data.available_reports || []).map((rt) => (
              <button key={rt} onClick={() => onReportType && onReportType(rt)}
                style={{ ...S.segBtn, ...(rt === reportType ? S.segOn : {}) }}>
                {rt === 'legacy_fut' ? 'LEGACY 3-WAY' : rt === 'tff_fut' ? 'TFF' : 'DISAGG'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* cohort chips */}
      <div style={S.chips}>
        {cohorts.map((c) => {
          const ix = last[c.key + '_idx'];
          const ext = ix != null && (ix > 90 || ix < 10);
          return (
            <div key={c.key} style={S.chip}>
              <div style={S.chipCl}>
                <span style={{ ...S.sw, background: c.color }} />{c.label}{c.primary ? ' ★' : ''}
              </div>
              <div style={S.chipNet}>{fmt(last[c.key])}</div>
              <div style={S.chipIdx}>COT idx{' '}
                <span style={{ color: ext ? (ix > 90 ? PAL.red : PAL.blue) : PAL.mut, fontWeight: 600 }}>
                  {ix != null ? ix.toFixed(1) : '—'}{ext ? (ix > 90 ? ' HIGH' : ' LOW') : ''}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* controls */}
      <div style={S.controls}>
        <div style={S.seg}>
          {WINDOWS.map((w) => (
            <button key={w.label} onClick={() => { setWinLen(w.w); setStart(Math.max(0, DATA.length - (w.w || DATA.length))); }}
              style={{ ...S.segBtn, ...(w.w === winLen ? S.segOn : {}) }}>{w.label}</button>
          ))}
        </div>
        <div style={S.legend}>
          {cohorts.map((c) => (
            <div key={c.key} onClick={() => setEnabled((p) => ({ ...p, [c.key]: !p[c.key] }))}
              style={{ ...S.lg, ...(enabled[c.key] ? {} : S.lgOff) }}>
              <span style={{ ...S.sw, background: c.color }} />{c.label}
            </div>
          ))}
          {/* price overlay toggle — disabled until a licensed feed is wired */}
          <div title="Price overlay requires a licensed market-data feed (off by default)."
            style={{ ...S.lg, ...S.lgOff, cursor: 'not-allowed' }}
            onClick={() => data.price_overlay_enabled && setLogScale((v) => !v)}>
            <span style={{ ...S.sw, background: '#fff', opacity: 0.4 }} />PRICE (log){data.price_overlay_enabled ? '' : ' · n/a'}
          </div>
        </div>
      </div>

      {/* scrubber */}
      {winLen !== 0 && (
        <div style={S.scrub}>
          <input type="range" min={0} max={Math.max(0, DATA.length - winLen)} value={start}
            onChange={(ev) => setStart(+ev.target.value)} style={{ flex: 1, accentColor: PAL.blue }} />
          <div style={S.rng}>{rangeLabel}</div>
        </div>
      )}

      {/* canvas + tooltip */}
      <div style={{ position: 'relative' }}>
        <canvas ref={canvasRef} style={{ display: 'block', width: '100%', marginTop: 8 }}
          onMouseMove={(ev) => setHoverX(ev.clientX - ev.currentTarget.getBoundingClientRect().left)}
          onMouseLeave={() => setHoverX(null)} />
        {tip && (
          <div style={{ ...S.tip, left: Math.min(tip.x + 14, (wrapRef.current?.clientWidth || 600) - 190), top: 40 }}>
            <div style={S.tipD}>{tip.d}</div>
            {tip.rows.map((r) => {
              const ext = r.idx != null && (r.idx > 90 || r.idx < 10);
              return (
                <div key={r.label} style={S.tipR}>
                  <span style={S.tipK}><span style={{ ...S.sw, background: r.color }} />{r.label}</span>
                  <span style={{ fontWeight: 600 }}>{fmt(r.net)}
                    {r.idx != null && <span style={{ color: ext ? PAL.red : PAL.mut }}> [{r.idx.toFixed(0)}]</span>}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div style={S.foot}>
        Net = long − short per cohort. Lower panel: net as a {data.lookback}-week stochastic (0–100);
        shaded bands mark &gt;90 / &lt;10 positioning extremes. ★ = primary speculative cohort. Source: CFTC (public domain).
      </div>
      {data.disclaimer && <div style={S.disc}>{data.disclaimer}</div>}
    </div>
  );
}

const MONO = "'IBM Plex Mono',ui-monospace,monospace";
const S = {
  wrap: { background: PAL.bg, color: PAL.txt, fontFamily: MONO, padding: '20px', borderRadius: 6, border: `1px solid ${PAL.line}` },
  top: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, borderBottom: `1px solid ${PAL.line}`, paddingBottom: 14, flexWrap: 'wrap' },
  h1: { fontFamily: "'Instrument Serif',serif", fontWeight: 400, fontSize: 38, lineHeight: 0.95, letterSpacing: 0.3 },
  tk: { color: PAL.mut, fontStyle: 'italic' },
  sub: { color: PAL.mut, fontSize: 11, marginTop: 7, letterSpacing: 0.4 },
  chips: { display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 },
  chip: { border: `1px solid ${PAL.line}`, background: '#0d0d0f', borderRadius: 4, padding: '8px 11px', minWidth: 132 },
  chipCl: { fontSize: 10, color: PAL.mut, letterSpacing: 0.5, display: 'flex', alignItems: 'center', gap: 6 },
  chipNet: { fontSize: 16, fontWeight: 600, marginTop: 3 },
  chipIdx: { fontSize: 10.5, color: PAL.mut, marginTop: 2 },
  sw: { width: 9, height: 9, borderRadius: 2, display: 'inline-block' },
  controls: { display: 'flex', gap: 14, alignItems: 'center', margin: '16px 0 4px', flexWrap: 'wrap' },
  seg: { display: 'inline-flex', border: `1px solid ${PAL.line}`, borderRadius: 4, overflow: 'hidden' },
  segBtn: { background: '#0d0d0f', color: PAL.mut, border: 0, padding: '6px 12px', font: 'inherit', fontSize: 11, cursor: 'pointer', fontFamily: MONO },
  segOn: { background: '#16161a', color: PAL.txt },
  legend: { display: 'flex', gap: 14, flexWrap: 'wrap', marginLeft: 'auto' },
  lg: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: PAL.mut, cursor: 'pointer', userSelect: 'none' },
  lgOff: { opacity: 0.34, textDecoration: 'line-through' },
  scrub: { display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 },
  rng: { fontSize: 10.5, color: PAL.mut, minWidth: 188, textAlign: 'right' },
  tip: { position: 'absolute', pointerEvents: 'none', zIndex: 9, background: '#101014', border: `1px solid ${PAL.line}`, borderRadius: 4, padding: '9px 11px', fontSize: 11, minWidth: 166 },
  tipD: { color: PAL.mut, fontSize: 10, marginBottom: 5, letterSpacing: 0.4 },
  tipR: { display: 'flex', justifyContent: 'space-between', gap: 14, lineHeight: 1.7 },
  tipK: { display: 'flex', alignItems: 'center', gap: 6, color: PAL.mut },
  foot: { color: PAL.dim, fontSize: 10, marginTop: 14, letterSpacing: 0.3 },
  disc: { color: PAL.dim, fontSize: 9.5, marginTop: 8, fontStyle: 'italic', borderTop: `1px solid ${PAL.line}`, paddingTop: 8 },
};
