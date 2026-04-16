import React, { useState, useEffect } from 'react';
import { COLORS, FONT } from '../utils/theme';
import { runPhase1Diagnostic, getPhase1Diagnostic } from '../utils/api';

function tpColor(rate) {
  if (rate == null) return COLORS.textDim;
  if (rate >= 60) return COLORS.green;
  if (rate >= 40) return COLORS.amber;
  return COLORS.red;
}

function downloadCSV(data, filename) {
  if (!data || data.length === 0) return;
  const cols = Object.keys(data[0]);
  const header = cols.join(',');
  const rows = data.map(r => cols.map(c => {
    const v = r[c];
    if (v == null) return '';
    if (typeof v === 'string' && v.includes(',')) return `"${v}"`;
    return v;
  }).join(','));
  const csv = [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

export default function Phase1DiagnosticPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Try loading cached results on mount
  useEffect(() => {
    getPhase1Diagnostic().then(r => {
      if (r && !r.error && r.summary) setData(r);
    }).catch(() => {});
  }, []);

  const runDiagnostic = async () => {
    setLoading(true);
    try {
      const r = await runPhase1Diagnostic();
      if (r && !r.error && r.summary) setData(r);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const s = data?.summary;

  return (
    <div style={{ marginTop: 12 }}>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '▾' : '▸'} Phase 1 Diagnostic — Q4/Q5 Classification
      </button>
      {expanded && (
        <div style={{ padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
          {/* Header with RUN + CSV buttons */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>PHASE 1 DIAGNOSTIC — Q4/Q5 CLASSIFICATION</span>
            <button onClick={runDiagnostic} disabled={loading}
              style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              {loading ? 'RUNNING (~60s)...' : data ? 'RE-RUN' : 'RUN DIAGNOSTIC'}
            </button>
            {data?.full_dataset?.length > 0 && (
              <button
                onClick={() => {
                  const d = new Date().toISOString().slice(0, 10);
                  downloadCSV(data.full_dataset, `q4q5_diagnostics_${d}.csv`);
                }}
                style={{ padding: '3px 12px', background: 'none', color: COLORS.textMuted,
                  border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
                CSV
              </button>
            )}
          </div>

          {!data && !loading && (
            <div style={{ color: COLORS.textDim, fontSize: 9 }}>
              Click RUN DIAGNOSTIC to build Q4/Q5 signal classification dataset. First run takes ~60 seconds.
            </div>
          )}

          {s && (
            <>
              {/* SUMMARY */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>SUMMARY</div>
                <div style={{ padding: '8px 12px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`, fontSize: 10 }}>
                  <div style={{ color: COLORS.white, marginBottom: 4 }}>
                    Total Q4/Q5 Signals: <span style={{ fontWeight: 'bold' }}>{s.total_q4_q5_signals}</span>
                    <span style={{ color: COLORS.textMuted, marginLeft: 12 }}>
                      (Q4: {s.q4_count}, Q5: {s.q5_count})
                    </span>
                  </div>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, marginBottom: 2 }}>
                    Date Range: {s.date_range?.[0]} to {s.date_range?.[1]}
                  </div>
                  <div style={{ color: COLORS.textDim, fontSize: 8 }}>
                    Generated: {s.generated_at?.slice(0, 19)?.replace('T', ' ')}
                    {s.from_cache && <span style={{ color: COLORS.amber, marginLeft: 6 }}>(cached)</span>}
                    {s.earnings_source && <span style={{ marginLeft: 12 }}>Earnings: {s.earnings_source}</span>}
                  </div>
                  {s.warnings?.length > 0 && (
                    <div style={{ marginTop: 4 }}>
                      {s.warnings.map((w, i) => (
                        <div key={i} style={{ color: COLORS.amber, fontSize: 8 }}>WARNING: {w}</div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* TP RATES */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>TP RATE BY DEFINITION</div>
                <div style={{ padding: '8px 12px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}` }}>
                  <table style={{ fontSize: 10, borderCollapse: 'collapse', width: '100%' }}>
                    <tbody>
                      {[
                        ['Strict', 'strict', 'fwd 6M max drawdown ≥10%'],
                        ['Moderate', 'moderate', 'fwd 6M max drawdown ≥7%'],
                        ['Loose', 'loose', 'negative fwd 3M return'],
                        ['Combined', 'combined', 'moderate OR fwd 3M < -5%'],
                      ].map(([label, key, desc]) => {
                        const rate = s.tp_rates?.[key];
                        return (
                          <tr key={key} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                            <td style={{ padding: '3px 6px', color: COLORS.white }}>{label}</td>
                            <td style={{ padding: '3px 6px', color: COLORS.textDim, fontSize: 8 }}>{desc}</td>
                            <td style={{ padding: '3px 6px', textAlign: 'right', fontWeight: 'bold',
                              color: tpColor(rate) }}>
                              {rate != null ? `${rate.toFixed(1)}%` : '--'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* TOP 5 TRUE POSITIVES */}
              {data.top_true_positives?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                    TOP {data.top_true_positives.length} TRUE POSITIVES (largest forward drawdowns)
                  </div>
                  <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        {['Date', 'Qtle', 'Fwd 6M DD', 'Fwd 3M', 'HY OAS', 'Fed Reg', 'Growth'].map(h => (
                          <th key={h} style={{ textAlign: h === 'Date' || h === 'Fed Reg' || h === 'Growth' ? 'left' : 'right',
                            color: COLORS.textDim, padding: '2px 5px', fontSize: 8 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_true_positives.map((r, i) => (
                        <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                          <td style={{ padding: '2px 5px', color: COLORS.green }}>{r.signal_date}</td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.white }}>{r.quintile}</td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.red, fontWeight: 'bold' }}>
                            {r.fwd_6m_max_drawdown != null ? `${(r.fwd_6m_max_drawdown).toFixed(1)}%` : '--'}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right',
                            color: (r.fwd_3m_return || 0) < 0 ? COLORS.red : COLORS.green }}>
                            {r.fwd_3m_return != null ? `${r.fwd_3m_return > 0 ? '+' : ''}${(r.fwd_3m_return).toFixed(1)}%` : '--'}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.white }}>
                            {r.hy_oas != null ? r.hy_oas.toFixed(0) : '--'}
                          </td>
                          <td style={{ padding: '2px 5px', color: COLORS.textMuted, fontSize: 8 }}>{r.fed_regime || '--'}</td>
                          <td style={{ padding: '2px 5px', color: COLORS.textMuted, fontSize: 8 }}>{r.growth_regime || '--'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* TOP 5 FALSE POSITIVES */}
              {data.top_false_positives?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                    TOP {data.top_false_positives.length} FALSE POSITIVES (Q5 signals with fwd 6M &gt; +5%)
                    {data.top_false_positives.length < 5 && (
                      <span style={{ color: COLORS.textDim }}> — {data.top_false_positives.length} of 5</span>
                    )}
                  </div>
                  <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        {['Date', 'Qtle', 'Fwd 6M Ret', 'Fwd 3M', 'HY OAS', 'Fed Reg', 'Earnings'].map(h => (
                          <th key={h} style={{ textAlign: h === 'Date' || h === 'Fed Reg' || h === 'Earnings' ? 'left' : 'right',
                            color: COLORS.textDim, padding: '2px 5px', fontSize: 8 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_false_positives.map((r, i) => (
                        <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                          <td style={{ padding: '2px 5px', color: COLORS.amber }}>{r.signal_date}</td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.white }}>{r.quintile}</td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.green, fontWeight: 'bold' }}>
                            {r.fwd_6m_return != null ? `+${(r.fwd_6m_return).toFixed(1)}%` : '--'}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right',
                            color: (r.fwd_3m_return || 0) < 0 ? COLORS.red : COLORS.green }}>
                            {r.fwd_3m_return != null ? `${r.fwd_3m_return > 0 ? '+' : ''}${(r.fwd_3m_return).toFixed(1)}%` : '--'}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.white }}>
                            {r.hy_oas != null ? r.hy_oas.toFixed(0) : '--'}
                          </td>
                          <td style={{ padding: '2px 5px', color: COLORS.textMuted, fontSize: 8 }}>{r.fed_regime || '--'}</td>
                          <td style={{ padding: '2px 5px', color: COLORS.textMuted, fontSize: 8 }}>{r.earnings_regime || '--'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* QUINTILE DISTRIBUTION */}
              {data.quintile_distribution && (
                <div>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                    QUINTILE DISTRIBUTION (reference — full sample)
                  </div>
                  <div style={{ padding: '6px 12px', background: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}` }}>
                    {Object.entries(data.quintile_distribution).map(([q, n]) => {
                      const maxN = Math.max(...Object.values(data.quintile_distribution));
                      const pct = maxN > 0 ? (n / maxN) * 100 : 0;
                      const isQ45 = q === 'Q4' || q === 'Q5';
                      return (
                        <div key={q} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                          <span style={{ color: isQ45 ? COLORS.amber : COLORS.textMuted, fontSize: 9, width: 22 }}>{q}</span>
                          <div style={{ flex: 1, height: 8, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden' }}>
                            <div style={{
                              width: `${pct}%`, height: '100%', borderRadius: 2,
                              background: isQ45 ? COLORS.amber : COLORS.cardBorder,
                            }} />
                          </div>
                          <span style={{ color: isQ45 ? COLORS.white : COLORS.textDim, fontSize: 8, width: 30, textAlign: 'right' }}>{n}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Missing data flags */}
              {s.missing_data_flags?.length > 0 && (
                <div style={{ marginTop: 8, fontSize: 8, color: COLORS.textDim }}>
                  {s.missing_data_flags.map((f, i) => (
                    <div key={i}>Missing: {f}</div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
