import React, { useEffect, useState, useCallback } from 'react';
import { getCotHeatmap, getCotDetail, getCotHealth } from '../utils/api.js';
import COTHeatmap from './COTHeatmap.jsx';
import COTDetailChart from './COTDetailChart.jsx';

/**
 * Multi-Asset COT Positioning module container.
 * Top: signature cross-asset heatmap (click a cell → detail).
 * Bottom: per-asset detail chart with a legacy <-> TFF/disagg report toggle.
 * A health strip surfaces fetch/validation staleness from /api/cot/health.
 */

const PAL = { bg: '#070708', line: '#26262c', txt: '#e6e6e8', mut: '#6f6f78', dim: '#48484f', red: '#f0463a', green: '#27c08a', amber: '#f5c451' };
const MONO = "'IBM Plex Mono',ui-monospace,monospace";

export default function COTModule() {
  const [heatmap, setHeatmap] = useState(null);
  const [symbol, setSymbol] = useState(null);
  const [reportType, setReportType] = useState('');
  const [detail, setDetail] = useState(null);
  const [health, setHealth] = useState(null);
  const [err, setErr] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // initial load: heatmap + health
  useEffect(() => {
    getCotHeatmap().then((h) => {
      setHeatmap(h);
      // auto-select the first asset that has data
      const first = h.groups.flatMap((g) => g.assets).find((a) => a.value != null);
      if (first) setSymbol(first.symbol);
    }).catch((e) => setErr(String(e)));
    getCotHealth().then(setHealth).catch(() => {});
  }, []);

  const loadDetail = useCallback((sym, rt) => {
    if (!sym) return;
    setLoadingDetail(true);
    getCotDetail(sym, { reportType: rt || '' })
      .then((d) => { setDetail(d); setReportType(d.report_type); })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoadingDetail(false));
  }, []);

  useEffect(() => { if (symbol) loadDetail(symbol, ''); }, [symbol, loadDetail]);

  const onSelect = (sym) => { setSymbol(sym); setReportType(''); };
  const onReportType = (rt) => { setReportType(rt); loadDetail(symbol, rt); };

  const hStatus = health?.last_run_status || 'unknown';
  const hColor = hStatus === 'ok' ? PAL.green : hStatus === 'failed' ? PAL.red : hStatus === 'degraded' ? PAL.amber : PAL.mut;

  return (
    <div style={{ fontFamily: MONO, color: PAL.txt, background: PAL.bg, minHeight: '100%', padding: '16px' }}>
      {/* health strip */}
      <div style={S.health}>
        <span style={{ ...S.dot, background: hColor }} />
        <span style={{ color: PAL.mut }}>PIPELINE</span>
        <span style={{ color: hColor, fontWeight: 600 }}>{hStatus.toUpperCase()}</span>
        {health?.last_success_at && <span style={{ color: PAL.dim }}>· last ok {fmtTs(health.last_success_at)}</span>}
        {health?.validation && (
          <span style={{ color: PAL.dim }}>
            · gates {Object.entries(health.validation).map(([k, v]) => `${k}:${v.ok ? '✓' : '✗'}`).join(' ')}
          </span>
        )}
        {health?.consecutive_failures > 0 && <span style={{ color: PAL.red }}>· {health.consecutive_failures} consecutive failures</span>}
      </div>

      {err && <div style={S.err}>COT module error: {err}</div>}

      <COTHeatmap data={heatmap} onSelect={onSelect} selected={symbol} />

      <div style={{ height: 16 }} />

      {loadingDetail && !detail && <div style={S.loading}>Loading {symbol}…</div>}
      {detail && (
        <COTDetailChart data={detail} reportType={reportType || detail.report_type} onReportType={onReportType} />
      )}
    </div>
  );
}

function fmtTs(iso) {
  try { return new Date(iso).toISOString().slice(0, 16).replace('T', ' ') + 'Z'; } catch { return iso; }
}

const S = {
  health: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 10.5, padding: '6px 10px', border: `1px solid ${PAL.line}`, borderRadius: 4, marginBottom: 12, flexWrap: 'wrap' },
  dot: { width: 7, height: 7, borderRadius: '50%', display: 'inline-block' },
  err: { color: PAL.red, fontSize: 12, padding: '8px 10px', border: `1px solid ${PAL.red}`, borderRadius: 4, marginBottom: 12 },
  loading: { color: PAL.mut, fontSize: 12, padding: 20 },
};
