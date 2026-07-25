import React, { useEffect, useState, useRef } from 'react';
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis,
  Tooltip, ReferenceLine, Legend, CartesianGrid,
} from 'recharts';
import { getOptionsSummary, getOptionsHealth, triggerOptionsSnapshot, getOptionsSurface } from '../utils/api.js';

/**
 * Options Positioning — I:SPX chain via Massive.com API.
 *
 * Layout (spec): header strip → pricing row → positioning row → gamma [MODEL]
 * panel → footer (exclusions, tier capability report, history depth).
 *
 * Honesty rules enforced in this UI:
 *  - PENDING / UNAVAILABLE are first-class states; no bare numbers from
 *    missing inputs.
 *  - OI/volume are never captioned as what the market is "pricing" — pricing
 *    language lives only in the surface row.
 *  - No holder-type attribution, no motive language, in any label.
 *  - OI level always renders next to its Δ once history exists.
 *  - The dealer-gamma assumption is printed in the panel, not hidden.
 */

const PAL = { bg: '#070708', line: '#26262c', txt: '#e6e6e8', mut: '#6f6f78', dim: '#48484f', red: '#f0463a', blue: '#5b9dff', green: '#27c08a', amber: '#f5c451' };
const MONO = "'IBM Plex Mono',ui-monospace,monospace";
const SERIF = "'Instrument Serif',serif";
const A_COLORS = { '1.00': '#5b9dff', '0.75': '#27c08a', '0.50': '#f5c451', '0.25': '#f0463a' };

const fmt = (n, d = 0) => (n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: 0 }));
const sign = (n, d = 0) => (n == null ? '—' : (n >= 0 ? '+' : '') + Number(n).toLocaleString('en-US', { maximumFractionDigits: d }));

export default function OptionsPositioningPanel() {
  const [data, setData] = useState(null);
  const [surf, setSurf] = useState(null);
  const [err, setErr] = useState(null);
  const [snapping, setSnapping] = useState(false);
  const [snapMsg, setSnapMsg] = useState(null);
  const [aOn, setAOn] = useState({ '1.00': true, '0.75': true, '0.50': true, '0.25': true });
  const pollRef = useRef(null);

  const load = () => {
    getOptionsSummary().then(setData).catch((e) => setErr(String(e)));
    getOptionsSurface().then(setSurf).catch(() => {});
  };
  useEffect(() => { load(); return () => clearTimeout(pollRef.current); }, []);

  const runSnapshot = () => {
    setSnapping(true); setSnapMsg(null);
    triggerOptionsSnapshot().then(() => poll(0)).catch((e) => { setSnapping(false); setErr(String(e)); });
  };
  const poll = (n) => {
    pollRef.current = setTimeout(async () => {
      try {
        const h = await getOptionsHealth();
        if (!h.snapshot_running && h.last_manual_run?.status && h.last_manual_run.status !== 'running') {
          setSnapping(false);
          setSnapMsg(`Snapshot ${h.last_manual_run.status}` + (h.last_manual_run.detail?.reason ? ` — ${h.last_manual_run.detail.reason}` : ''));
          load();
          return;
        }
      } catch { /* keep polling */ }
      if (n < 60) poll(n + 1); else { setSnapping(false); setSnapMsg('Still running — reload shortly.'); }
    }, 3000);
  };

  if (err) return <Shell><div style={S.err}>Options module error: {err}</div></Shell>;
  if (!data) return <Shell><div style={{ color: PAL.mut, padding: 20 }}>Loading…</div></Shell>;

  const tier = data.tier || {};
  const m = data.metrics;
  const ok = m && m.status === 'ok';

  return (
    <Shell>
      {/* tier gates */}
      {tier.state === 'insufficient_plan' && (
        <div style={S.gate}>
          <div style={{ fontFamily: SERIF, fontSize: 24 }}>Options data requires an upgraded plan</div>
          <div style={{ color: PAL.mut, marginTop: 6 }}>{tier.message}</div>
        </div>
      )}
      {tier.state === 'unprobed' && (
        <div style={S.notice}>API capabilities not yet probed — run <code>scripts/probe_massive.py</code> on the server. {tier.message}</div>
      )}
      {tier.state === 'unreachable' && (
        <div style={S.notice}>Massive API unreachable at last probe: {tier.message}</div>
      )}

      {/* 1 ── header strip */}
      <div style={S.head}>
        <div>
          <div style={{ fontFamily: SERIF, fontSize: 34, lineHeight: 0.95 }}>Options Positioning <span style={{ color: PAL.mut, fontStyle: 'italic' }}>/ SPX</span></div>
          <div style={S.sub}>
            MASSIVE.COM CHAIN SNAPSHOT · DAILY · {data.capabilities?.recency?.classification?.toUpperCase() || 'RECENCY UNKNOWN'}
            {' '}· HISTORY {data.history_depth} SESSION{data.history_depth === 1 ? '' : 'S'}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          {ok ? (
            <>
              <div style={{ fontSize: 26, fontWeight: 600 }}>{fmt(m.spot, 2)}</div>
              <div style={{ fontSize: 11, color: PAL.mut }}>
                1d <Chg v={m.spot_chg_1d_pct} /> · 5d <Chg v={m.spot_chg_5d_pct} /> · as of {m.snap_date}
                {m.spot_source && m.spot_source !== 'massive:chain' && ` · spot src ${m.spot_source}`}
              </div>
            </>
          ) : (
            <div style={{ color: PAL.mut, fontSize: 12 }}>No snapshot stored yet</div>
          )}
          <button onClick={runSnapshot} disabled={snapping} style={S.btn(snapping)}>
            {snapping ? '⧗ Snapshotting…' : '⬇ Run snapshot now'}
          </button>
          {snapMsg && <div style={{ fontSize: 10, color: PAL.mut, marginTop: 4 }}>{snapMsg}</div>}
        </div>
      </div>

      {!ok && (
        <div style={S.pendingBig}>
          PENDING — no chain snapshot stored yet. The store builds forward only from our own
          daily snapshots (no third-party backfill). Take the first snapshot to start history.
        </div>
      )}

      {ok && <>
        {/* 2 ── pricing row (surface metrics — the only place pricing claims live) */}
        <SectionTitle t="PRICING — VOLATILITY SURFACE" asof={m.snap_date}
          note={data.surface_history?.reconstructed
            ? `history: ${fmt(data.surface_history.reconstructed)} reconstructed${data.surface_history.live ? ` + ${fmt(data.surface_history.live)} live` : ''}${data.surface_history.first_live ? ` since ${data.surface_history.first_live}` : ''}`
            : null} />
        <div style={S.cards}>
          <Card label="ATM IV 30D" tip={m.surface.methods?.atm}
            value={m.surface.atm_iv_30d != null ? m.surface.atm_iv_30d.toFixed(2) + '%' : null}
            pct={data.percentiles?.atm_iv_30d} />
          <Card label="25Δ RISK REVERSAL / ATM" tip={`(25Δ put IV − 25Δ call IV) / ATM · expiry ${m.surface.rr_25d?.expiry || '—'}`}
            value={m.surface.rr_25d ? m.surface.rr_25d.value.toFixed(4) : null}
            pct={data.percentiles?.rr_25d} />
          <Card label="VRP (30D IV − 30D RV)" tip={m.surface.methods?.vrp}
            value={m.surface.vrp != null ? m.surface.vrp.toFixed(2) + ' pts' : null}
            pct={data.percentiles?.vrp}
            sub={<VrpDetail s={m.surface} sessions={m.history.sessions} />} />
          <div style={S.tsCard}>
            <div style={S.cardLabel} title="Constant-maturity: interpolated between listed expiries, linear in total variance (σ²T). Same construction as the surface grid.">IV TERM STRUCTURE (ATM) <span style={{ color: PAL.dim }}>· const-maturity</span></div>
            {m.surface.term_structure?.length >= 2 ? (
              <ResponsiveContainer width="100%" height={90}>
                <LineChart data={m.surface.term_structure} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                  <XAxis dataKey="days" tick={{ fontSize: 9, fill: PAL.mut }} stroke={PAL.line} />
                  <YAxis tick={{ fontSize: 9, fill: PAL.mut }} stroke={PAL.line} domain={['auto', 'auto']} />
                  <Tooltip contentStyle={S.tt} formatter={(v) => [v + '%', 'ATM IV']} labelFormatter={(d, p) => `${p?.[0]?.payload?.expiry} (${d}d)`} />
                  <Line dataKey="atm_iv" stroke={PAL.blue} strokeWidth={1.5} dot={{ r: 2 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : <Pending text="needs ≥2 expiries with IV" />}
          </div>
        </div>

        {/* 2b ── volatility surface (delta × tenor grid + smiles) */}
        {surf?.status === 'ok' && <VolSurface surf={surf} />}

        {/* 3 ── positioning row */}
        <SectionTitle t="POSITIONING — OPEN INTEREST" asof={m.snap_date}
          note={m.positioning.delta_status !== 'ok' ? m.positioning.delta_status : (m.positioning.delta5_status !== 'ok' ? `ΔOI 5d ${m.positioning.delta5_status}` : null)} />
        <div style={{ fontSize: 9.5, color: PAL.dim, margin: '-2px 0 8px' }}>
          OI has no historical source — OPRA aggregates (REST or flat file) carry none — so ΔOI
          accumulates forward-only from our daily snapshots since {m.history.first_date}. Never approximated from volume.
        </div>
        <div style={S.posRow}>
          <div style={S.posChart}>
            <div style={S.cardLabel}>ΔOI 1D BY EXPIRY BUCKET (contracts)</div>
            {m.positioning.delta_status === 'ok' ? (
              <ResponsiveContainer width="100%" height={170}>
                <BarChart data={bucketBars(m.positioning.buckets, 'doi_1d')} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
                  <CartesianGrid stroke={PAL.line} vertical={false} />
                  <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: PAL.mut }} stroke={PAL.line} />
                  <YAxis tick={{ fontSize: 9, fill: PAL.mut }} stroke={PAL.line} tickFormatter={(v) => fmt(v)} />
                  <Tooltip contentStyle={S.tt} formatter={(v, name) => [sign(v), name]} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <ReferenceLine y={0} stroke={PAL.mut} />
                  <Bar dataKey="calls" fill={PAL.blue} isAnimationActive={false} />
                  <Bar dataKey="puts" fill={PAL.red} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            ) : <Pending text={m.positioning.delta_status} />}
            <div style={{ ...S.cardLabel, marginTop: 10 }}>P/C OI RATIO BY BUCKET</div>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
              {Object.entries(m.positioning.buckets).map(([name, b]) => (
                <div key={name} style={{ minWidth: 120 }}>
                  <span style={{ color: PAL.mut, fontSize: 10 }}>{name} </span>
                  <span style={{ fontWeight: 600 }}>{b.pc_oi_ratio ?? '—'}</span>
                  <Spark pts={(data.histories[`positioning.buckets.${name}.pc_oi_ratio`] || []).map(([, v]) => v)} />
                </div>
              ))}
            </div>
          </div>
          <div style={S.posTable}>
            <div style={S.cardLabel}>TOP 15 STRIKES BY |ΔOI 5D|</div>
            {m.positioning.delta5_status === 'ok' && m.positioning.top_delta?.length ? (
              <table style={S.table}>
                <thead><tr>{['STRIKE', '%SPOT', 'EXP', 'TYPE', 'OI', 'ΔOI 5D', 'ΔOI 1D', 'VOL/OI'].map(h => <th key={h} style={S.th}>{h}</th>)}</tr></thead>
                <tbody>
                  {m.positioning.top_delta.map((r) => (
                    <tr key={r.ticker}>
                      <td style={S.td}>{fmt(r.strike)}</td>
                      <td style={S.td}>{sign(r.pct_from_spot, 1)}%</td>
                      <td style={S.td}>{r.expiry.slice(5)}</td>
                      <td style={{ ...S.td, color: r.ctype === 'call' ? PAL.blue : PAL.red }}>{r.ctype[0].toUpperCase()}</td>
                      <td style={S.td}>{fmt(r.oi)}</td>
                      <td style={{ ...S.td, color: r.doi_5d >= 0 ? PAL.green : PAL.red }}>{sign(r.doi_5d)}</td>
                      <td style={S.td}>{sign(r.doi_1d)}</td>
                      <td style={S.td}>{r.vol_oi ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <Pending text={m.positioning.delta5_status} />}
            <div style={{ ...S.cardLabel, marginTop: 10 }}>TOP 10 STRIKES BY DAY VOLUME <span style={{ color: PAL.dim }}>(activity — separate from OI)</span></div>
            <table style={S.table}>
              <thead><tr>{['STRIKE', '%SPOT', 'TOTAL VOL', 'CALL VOL', 'PUT VOL'].map(h => <th key={h} style={S.th}>{h}</th>)}</tr></thead>
              <tbody>
                {m.positioning.top_volume.map((r) => (
                  <tr key={r.strike}>
                    <td style={S.td}>{fmt(r.strike)}</td>
                    <td style={S.td}>{sign(r.pct_from_spot, 1)}%</td>
                    <td style={S.td}>{fmt(r.volume)}</td>
                    <td style={S.td}>{fmt(r.call_volume)}</td>
                    <td style={S.td}>{fmt(r.put_volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* trade-flow panel: strictly capability-gated */}
        {!data.flow?.available && (
          <div style={S.flowUnavail}>TRADE-FLOW CLASSIFICATION: {data.flow?.message || 'unavailable on current plan'} — quote-rule classification requires trades + quotes access; no tick-test approximation is used.</div>
        )}

        {/* 4 ── dealer gamma [MODEL] */}
        <SectionTitle t={<span>DEALER GAMMA <span style={S.modelBadge}>MODEL</span></span>} asof={m.snap_date} />
        <div style={S.gammaPanel}>
          <div style={{ color: PAL.amber, fontSize: 11, marginBottom: 6 }}>
            {m.gamma.assumption} Curves show four dealer-long-call shares (a); crossings are listed per scenario, never collapsed to one number.
          </div>
          <div style={{ display: 'flex', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
            {Object.keys(m.gamma.curves).map((a) => (
              <span key={a} onClick={() => setAOn((p) => ({ ...p, [a]: !p[a] }))}
                style={{ cursor: 'pointer', fontSize: 10.5, color: aOn[a] ? A_COLORS[a] : PAL.dim, textDecoration: aOn[a] ? 'none' : 'line-through', userSelect: 'none' }}>
                ■ a={a}
              </span>
            ))}
          </div>
          <ResponsiveContainer width="100%" height={230}>
            <LineChart data={gammaData(m.gamma)} margin={{ top: 4, right: 12, bottom: 0, left: 6 }}>
              <CartesianGrid stroke={PAL.line} vertical={false} />
              <XAxis dataKey="spot" tick={{ fontSize: 9, fill: PAL.mut }} stroke={PAL.line} tickFormatter={(v) => fmt(v)} />
              <YAxis tick={{ fontSize: 9, fill: PAL.mut }} stroke={PAL.line} tickFormatter={(v) => '$' + compact(v)} />
              <Tooltip contentStyle={S.tt} formatter={(v, name) => ['$' + fmt(v), `net γ (a=${name})`]} labelFormatter={(v) => `hypothetical spot ${fmt(v)}`} />
              <ReferenceLine y={0} stroke={PAL.mut} />
              <ReferenceLine x={m.spot} stroke={PAL.txt} strokeDasharray="3 3" label={{ value: 'spot', fill: PAL.mut, fontSize: 9 }} />
              {Object.entries(m.gamma.curves).map(([a]) => aOn[a] && (
                <Line key={a} dataKey={a} stroke={A_COLORS[a]} strokeWidth={1.4} dot={false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 10.5, marginTop: 6 }}>
            <span style={{ color: PAL.mut }}>Units: {m.gamma.units}</span>
            <span>Gross at spot: <b>${compact(m.gamma.gross_at_spot)}</b></span>
            {Object.entries(m.gamma.net_at_spot).map(([a, v]) => (
              <span key={a} style={{ color: A_COLORS[a] }}>net(a={a}): ${compact(v)}</span>
            ))}
          </div>
          <div style={{ fontSize: 10.5, marginTop: 4 }}>
            {Object.entries(m.gamma.crossings).map(([a, xs]) => (
              <span key={a} style={{ marginRight: 16, color: A_COLORS[a] }}>
                flip a={a}: {xs.length ? xs.map((x) => fmt(x)).join(', ') : `no crossing in ±${m.gamma.sweep_range_pct ?? 25}%`}
              </span>
            ))}
          </div>
          {m.gamma.comparison && (
            <div style={{ fontSize: 10, marginTop: 6, padding: '5px 8px', border: `1px solid ${PAL.line}`, borderRadius: 3 }}>
              <span style={{ color: PAL.mut }}>FILTER SENSITIVITY (positioning asks "what traded"; gamma asks "what exposure exists"):</span>
              <div style={{ marginTop: 2 }}>
                unfiltered <b>${compact(m.gamma.comparison.unfiltered.gross_at_spot)}</b> gross · flip {fmt(m.gamma.comparison.unfiltered.flip_1_00) || '—'} ({fmt(m.gamma.comparison.unfiltered.n_contracts)} contracts)
                {' · '}filtered <b>${compact(m.gamma.comparison.filtered.gross_at_spot)}</b> gross · flip {fmt(m.gamma.comparison.filtered.flip_1_00) || '—'} ({fmt(m.gamma.comparison.filtered.n_contracts)} contracts)
              </div>
              <div style={{ color: m.gamma.comparison.immaterial ? PAL.dim : PAL.amber }}>
                a=1.00 flip gap: {m.gamma.comparison.flip_delta_pct != null ? m.gamma.comparison.flip_delta_pct + '% of spot' : '—'} · {m.gamma.comparison.note}
              </div>
            </div>
          )}
          <div style={{ color: PAL.dim, fontSize: 9.5, marginTop: 4 }}>
            BS re-pricing at each hypothetical spot with each contract's snapshot IV held fixed (r=4%, q=1.5%), swept ±{m.gamma.sweep_range_pct ?? 25}%. Displayed: {m.gamma.basis || 'unfiltered'}.
            {' '}{m.gamma.n_contracts_used} contracts used; {m.gamma.skipped.count} skipped ({fmt(m.gamma.skipped.oi)} OI) — {fmt(m.gamma.skipped.missing_iv ?? 0)} missing IV, {fmt(m.gamma.skipped.zero_oi ?? 0)} zero OI.
          </div>
        </div>

        {/* 5 ── footer: exclusions, tier report, history depth */}
        <div style={S.footer}>
          <span>EXCLUDED — band ±{(m.hygiene.band_pct * 100).toFixed(0)}%: {fmt(m.hygiene.band.count)} strikes / {fmt(m.hygiene.band.oi)} OI</span>
          <span title={`stale basis: ${m.hygiene.stale_basis || '1-session volume/OI'}`}>stale vol/OI&lt;{m.hygiene.stale_threshold}: {fmt(m.hygiene.stale.count)} strikes / {fmt(m.hygiene.stale.oi)} OI ({(m.hygiene.stale_basis || '1-session').split(' ')[0]})</span>
          <span>missing OI: {fmt(m.hygiene.missing_oi.count)}</span>
          <span>kept: {fmt(m.hygiene.kept_count)} / {fmt(m.hygiene.kept_oi)} OI</span>
          <span>TIER: {data.capabilities?.detected_tier || 'unprobed'}</span>
          <span>{data.history_depth} sessions accumulated (since {m.history.first_date})</span>
        </div>
      </>}
    </Shell>
  );
}

// ── volatility surface (delta × tenor grid + smile) ──────────────────────────
function ivColor(v, lo, hi) {
  if (v == null) return 'transparent';
  const t = hi > lo ? Math.max(0, Math.min(1, (v - lo) / (hi - lo))) : 0.5;
  // blue (low) → amber (mid) → red (high), muted to sit on the dark panel
  const stops = [[59, 110, 165], [190, 150, 70], [200, 70, 58]];
  const seg = t < 0.5 ? [stops[0], stops[1], t * 2] : [stops[1], stops[2], (t - 0.5) * 2];
  const [a, b, f] = seg;
  const c = a.map((x, i) => Math.round(x + (b[i] - x) * f));
  return `rgba(${c[0]},${c[1]},${c[2]},0.85)`;
}

const VolSurface = ({ surf }) => {
  const [mode, setMode] = useState('raw');
  const hasSmoothed = (surf.smoothed_grid || []).length > 0;
  const activeGrid = mode === 'smoothed' && hasSmoothed ? surf.smoothed_grid : surf.grid;
  const cells = activeGrid.flatMap((r) => Object.values(r.cells)).filter((v) => v != null);
  const lo = Math.min(...cells), hi = Math.max(...cells);
  const cov = surf.coverage || {};
  const arb = surf.arbitrage || {};
  const cal = arb.calendar_violations || [];
  const fly = arb.butterfly || {};
  const flyS = arb.butterfly_smoothed || {};
  const smile = (surf.smiles || []).sort((a, b) => a.days - b.days);
  const smileData = smile.length ? mergeSmiles(smile) : [];
  const Tab = ({ id, label }) => (
    <span onClick={() => setMode(id)} style={{ cursor: 'pointer', marginRight: 10, fontSize: 9.5,
      color: mode === id ? PAL.txt : PAL.dim, borderBottom: mode === id ? `1px solid ${PAL.blue}` : 'none' }}>{label}</span>
  );

  return (
    <>
      <SectionTitle t="VOLATILITY SURFACE" asof={surf.asof}
        note={`${cov.expiries_used} expiries · ${fmt(cov.quality_rows)} quality contracts`} />
      <div style={S.surfWrap}>
        {/* delta × tenor heatmap */}
        <div style={{ overflowX: 'auto' }}>
          <div style={{ ...S.cardLabel, display: 'flex', justifyContent: 'space-between' }}>
            <span>CONSTANT-MATURITY IV GRID <span style={{ color: PAL.dim }}>(vol %, by 30d-delta bucket)</span></span>
            <span>
              <Tab id="raw" label="raw (diagnostic)" />
              {hasSmoothed && <Tab id="smoothed" label="SVI arb-free" />}
            </span>
          </div>
          <table style={S.surfTable}>
            <thead><tr>
              <th style={S.surfTh}>TENOR</th>
              {surf.columns.map((c) => <th key={c} style={S.surfTh}>{c}</th>)}
            </tr></thead>
            <tbody>
              {activeGrid.map((row) => (
                <tr key={row.tenor}>
                  <td style={{ ...S.surfTd, color: PAL.mut, textAlign: 'left' }}>{row.tenor}d</td>
                  {surf.columns.map((c) => {
                    const v = row.cells[c];
                    return <td key={c} style={{ ...S.surfTd, background: ivColor(v, lo, hi), color: v == null ? PAL.dim : '#0a0a0b' }}>
                      {v == null ? '·' : v.toFixed(1)}
                    </td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 9, color: PAL.dim, marginTop: 4 }}>
            {mode === 'smoothed' ? surf.smoothed_grid_label : surf.grid_label} · {fmt(lo, 1)}%
            <span style={{ background: `linear-gradient(90deg, ${ivColor(lo, lo, hi)}, ${ivColor((lo + hi) / 2, lo, hi)}, ${ivColor(hi, lo, hi)})`, padding: '0 20px', margin: '0 4px', borderRadius: 2 }} />
            {fmt(hi, 1)}% · blank = not bracketed (not extrapolated)
          </div>
          <div style={{ fontSize: 9.5, color: PAL.dim, marginTop: 4 }}>
            butterfly violations: raw <b style={{ color: fly.violations ? PAL.amber : PAL.txt }}>{fly.violations || 0}</b>
            {' → '}smoothed <b style={{ color: (flyS.violations || 0) ? PAL.amber : PAL.green }}>{flyS.violations || 0}</b> / {fmt(fly.checked_triples)} triples
            {' · '}25Δ RR raw {surf.rr_25d_raw != null ? surf.rr_25d_raw.toFixed(4) : '—'} · smoothed <b style={{ color: PAL.txt }}>{surf.rr_25d_smoothed != null ? surf.rr_25d_smoothed.toFixed(4) : '—'}</b>
          </div>
        </div>

        {/* smiles */}
        <div>
          <div style={S.cardLabel}>SMILE — IV vs MONEYNESS <span style={{ color: PAL.dim }}>(nearest {smile.map((s) => `${s.days}d`).join(' / ')})</span></div>
          {smileData.length >= 2 ? (
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={smileData} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                <CartesianGrid stroke={PAL.line} vertical={false} />
                <XAxis dataKey="m" type="number" domain={['dataMin', 'dataMax']} tick={{ fontSize: 9, fill: PAL.mut }} stroke={PAL.line} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                <YAxis tick={{ fontSize: 9, fill: PAL.mut }} stroke={PAL.line} domain={['auto', 'auto']} tickFormatter={(v) => v.toFixed(0)} />
                <Tooltip contentStyle={S.tt} formatter={(v, n) => [v?.toFixed(2) + '%', n]} labelFormatter={(v) => `${(v * 100).toFixed(1)}% from spot`} />
                <ReferenceLine x={0} stroke={PAL.mut} strokeDasharray="3 3" />
                {smile.map((s, i) => (
                  <Line key={s.expiry} dataKey={`d${s.days}`} name={`${s.days}d`} stroke={[PAL.blue, PAL.amber, PAL.green][i % 3]} strokeWidth={1.3} dot={false} connectNulls isAnimationActive={false} />
                ))}
                <Legend wrapperStyle={{ fontSize: 10 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : <Pending text="not enough strikes for a smile" />}
        </div>
      </div>

      {/* arbitrage + limits footer */}
      <div style={{ ...S.footer, marginTop: 8 }}>
        <span style={{ color: cal.length ? PAL.amber : PAL.dim }}>
          calendar arb: {cal.length ? `${cal.length} violation${cal.length > 1 ? 's' : ''}` : 'none'}
        </span>
        <span style={{ color: (flyS.violations || 0) ? PAL.amber : PAL.dim }}>
          butterfly: raw {fly.violations || 0} → SVI {flyS.violations || 0} of {fmt(fly.checked_triples)}
        </span>
        <span>excluded — no IV: {fmt(cov.excluded?.no_iv)} · IV out of 3–150%: {fmt(cov.excluded?.iv_out_of_range)} · {'>'}400d: {fmt(cov.excluded?.beyond_max_dte)}</span>
        <span style={{ color: PAL.dim }} title={surf.smoothed_method}>IV vendor-computed from last prints (no quotes on plan) · r=4% q=1.5% held constant · SVI arb-free layer available</span>
      </div>
    </>
  );
};

function mergeSmiles(smiles) {
  // merge per-expiry points onto a shared moneyness axis; key each series d<days>
  const byM = new Map();
  for (const s of smiles) {
    for (const p of s.points) {
      const key = Math.round(p.moneyness * 1000) / 1000;
      if (!byM.has(key)) byM.set(key, { m: key });
      // use OTM side per type so the smile is the tradable wing: puts below spot, calls above
      const otm = (p.ctype === 'put' && p.moneyness <= 0) || (p.ctype === 'call' && p.moneyness >= 0);
      if (otm) byM.get(key)[`d${s.days}`] = p.iv;
    }
  }
  return [...byM.values()].sort((a, b) => a.m - b.m);
}

// ── helpers ────────────────────────────────────────────────────────────────
function bucketBars(buckets, key) {
  return Object.entries(buckets).map(([bucket, b]) => ({
    bucket, calls: b.call?.[key], puts: b.put?.[key],
  }));
}

function gammaData(g) {
  return g.spots.map((s, i) => {
    const row = { spot: s };
    for (const [a, curve] of Object.entries(g.curves)) row[a] = curve[i];
    return row;
  });
}

function compact(v) {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (abs >= 1e3) return (v / 1e3).toFixed(0) + 'k';
  return String(Math.round(v));
}

const VrpDetail = ({ s, sessions }) => {
  const rv = s.realised || {}, pk = s.realised_parkinson || {}, vw = s.vrp_by_window || {};
  const trip = (o) => ['10', '20', '30'].map((w) => o[w] == null ? '—' : fmt(o[w], 1)).join(' / ');
  if (s.vrp == null && !rv['30']) return <>RV30 needs 30 daily closes (have {fmt(s.realised_days || sessions)})</>;
  return (
    <div>
      <div>VRP vs RV10/20/30: <b style={{ color: PAL.txt }}>{trip(vw)}</b> pts</div>
      <div>RV c2c: {trip(rv)} · Parkinson: {trip(pk)} · ^GSPC</div>
      {s.rv_window_flag && (
        <div style={{ color: PAL.amber }}>⚠ RV30 carries a session RV20 has dropped — VRP headline window-sensitive.</div>
      )}
    </div>
  );
};

const Chg = ({ v }) => v == null ? <span style={{ color: PAL.dim }}>PENDING</span>
  : <span style={{ color: v >= 0 ? PAL.green : PAL.red }}>{sign(v, 2)}%</span>;

const Pending = ({ text }) => (
  <div style={{ color: PAL.dim, fontSize: 11, padding: '14px 4px', fontStyle: 'italic' }}>{text || 'PENDING'}</div>
);

const SectionTitle = ({ t, asof, note }) => (
  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, margin: '18px 0 8px', borderBottom: `1px solid ${PAL.line}`, paddingBottom: 5 }}>
    <span style={{ fontSize: 11, letterSpacing: 1, color: '#8a8a92' }}>{t}</span>
    {asof && <span style={{ fontSize: 9, color: PAL.dim }}>as of {asof}</span>}
    {note && <span style={{ fontSize: 9, color: PAL.amber }}>{note}</span>}
  </div>
);

const Card = ({ label, value, pct, sub, tip }) => (
  <div style={S.card} title={tip}>
    <div style={S.cardLabel}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 600, fontFamily: SERIF }}>{value ?? <span style={{ color: PAL.dim, fontSize: 14, fontStyle: 'italic' }}>PENDING</span>}</div>
    {pct && (
      <div style={{ fontSize: 10, color: PAL.mut }}>
        {pct.status === 'ok'
          ? <>1Y pctl <b style={{ color: PAL.txt }}>{pct.percentile}%</b> ({pct.sessions} sessions)</>
          : <>pctl PENDING — {pct.sessions}/{60} sessions</>}
      </div>
    )}
    {sub && <div style={{ fontSize: 9, color: PAL.dim, marginTop: 2 }}>{sub}</div>}
  </div>
);

const Spark = ({ pts }) => {
  const vals = (pts || []).filter((v) => v != null);
  if (vals.length < 2) return <span style={{ color: PAL.dim, fontSize: 9 }}> · history pending</span>;
  const min = Math.min(...vals), max = Math.max(...vals), rng = max - min || 1;
  const W = 60, H = 14;
  const d = vals.map((v, i) => `${(i / (vals.length - 1)) * W},${H - ((v - min) / rng) * H}`).join(' ');
  return <svg width={W} height={H} style={{ marginLeft: 6, verticalAlign: 'middle' }}><polyline points={d} fill="none" stroke={PAL.mut} strokeWidth="1" /></svg>;
};

const Shell = ({ children }) => (
  <div style={{ fontFamily: MONO, color: PAL.txt, background: PAL.bg, minHeight: '100%', padding: 16 }}>{children}</div>
);

const S = {
  err: { color: PAL.red, fontSize: 12, padding: '8px 10px', border: `1px solid ${PAL.red}`, borderRadius: 4 },
  gate: { border: `1px solid ${PAL.amber}66`, borderRadius: 4, padding: 20, marginBottom: 14, textAlign: 'center' },
  notice: { border: `1px solid ${PAL.line}`, borderRadius: 4, padding: '8px 12px', marginBottom: 12, fontSize: 11, color: PAL.amber },
  head: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, borderBottom: `1px solid ${PAL.line}`, paddingBottom: 12, flexWrap: 'wrap' },
  sub: { color: PAL.mut, fontSize: 10.5, marginTop: 6, letterSpacing: 0.4 },
  btn: (busy) => ({ marginTop: 6, padding: '4px 12px', background: 'transparent', color: busy ? PAL.mut : PAL.green, border: `1px solid ${busy ? PAL.line : PAL.green}66`, borderRadius: 3, fontFamily: MONO, fontSize: 10.5, cursor: busy ? 'default' : 'pointer' }),
  pendingBig: { border: `1px dashed ${PAL.line}`, borderRadius: 4, padding: 24, marginTop: 16, color: PAL.mut, fontSize: 12, textAlign: 'center' },
  cards: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 },
  card: { border: `1px solid ${PAL.line}`, borderRadius: 4, padding: '10px 12px', background: '#0d0d0f' },
  tsCard: { border: `1px solid ${PAL.line}`, borderRadius: 4, padding: '10px 12px', background: '#0d0d0f', minWidth: 220 },
  cardLabel: { fontSize: 9.5, color: PAL.mut, letterSpacing: 0.6, marginBottom: 4 },
  posRow: { display: 'grid', gridTemplateColumns: 'minmax(300px, 5fr) minmax(340px, 6fr)', gap: 12 },
  posChart: { border: `1px solid ${PAL.line}`, borderRadius: 4, padding: '10px 12px', background: '#0d0d0f' },
  posTable: { border: `1px solid ${PAL.line}`, borderRadius: 4, padding: '10px 12px', background: '#0d0d0f', overflowX: 'auto' },
  table: { borderCollapse: 'collapse', width: '100%', fontSize: 10 },
  th: { textAlign: 'right', color: PAL.dim, fontWeight: 400, padding: '2px 6px', borderBottom: `1px solid ${PAL.line}` },
  td: { textAlign: 'right', padding: '2px 6px', borderBottom: `1px solid #141418` },
  tt: { background: '#101014', border: `1px solid ${PAL.line}`, fontSize: 10, fontFamily: MONO },
  flowUnavail: { marginTop: 12, padding: '6px 10px', border: `1px dashed ${PAL.line}`, borderRadius: 4, color: PAL.dim, fontSize: 10 },
  modelBadge: { background: PAL.amber, color: '#000', fontSize: 9, padding: '1px 6px', borderRadius: 3, marginLeft: 6, fontWeight: 700 },
  gammaPanel: { border: `1px solid ${PAL.amber}44`, borderRadius: 4, padding: '10px 12px', background: '#0d0d0f' },
  surfWrap: { display: 'grid', gridTemplateColumns: 'minmax(320px, 5fr) minmax(300px, 4fr)', gap: 12 },
  surfTable: { borderCollapse: 'collapse', fontSize: 10, fontFamily: MONO },
  surfTh: { color: PAL.dim, fontWeight: 400, padding: '2px 8px', borderBottom: `1px solid ${PAL.line}`, textAlign: 'right' },
  surfTd: { textAlign: 'right', padding: '3px 8px', fontVariantNumeric: 'tabular-nums', minWidth: 40 },
  footer: { display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 14, paddingTop: 8, borderTop: `1px solid ${PAL.line}`, fontSize: 9.5, color: PAL.dim },
};
