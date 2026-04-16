import React, { useState, useEffect } from 'react';
import { COLORS, FONT } from '../utils/theme';
import { runPhase2Analysis, getPhase2Analysis } from '../utils/api';

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
  const blob = new Blob([header + '\n' + rows.join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

export default function Phase2FilterPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    getPhase2Analysis().then(r => {
      if (r && !r.error) setData(r);
    }).catch(() => {});
  }, []);

  const run = async () => {
    setLoading(true);
    try {
      const r = await runPhase2Analysis(true);
      if (r && !r.error) setData(r);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const rc = data?.rule_comparisons;
  const winner = data?.winning_rule;

  return (
    <div style={{ marginTop: 12 }}>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '▾' : '▸'} Phase 2 — Filter Rule Analysis
      </button>
      {expanded && (
        <div style={{ padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>PHASE 2 — FILTER RULE ANALYSIS</span>
            <button onClick={run} disabled={loading}
              style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              {loading ? 'RUNNING (~30s)...' : data ? 'RE-RUN' : 'RUN ANALYSIS'}
            </button>
            {data?.filtered_signals && ['rule_a', 'rule_b', 'rule_c'].map(key => (
              <button key={key}
                onClick={() => downloadCSV(data.filtered_signals[key],
                  `filtered_signal_${key}_${new Date().toISOString().slice(0,10)}.csv`)}
                style={{ padding: '2px 8px', background: 'none', color: COLORS.textMuted,
                  border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
                {key.replace('_', ' ').toUpperCase()}
              </button>
            ))}
            {data?.from_cache && (
              <span style={{ color: COLORS.amber, fontSize: 8 }}>(cached)</span>
            )}
          </div>

          {!data && !loading && (
            <div style={{ color: COLORS.textDim, fontSize: 9 }}>
              Requires Phase 1 data. Run Phase 1 first, then click RUN ANALYSIS.
            </div>
          )}

          {data && (
            <>
              {/* UNIVARIATE RANKING */}
              {data.univariate_rankings?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                    UNIVARIATE RANKING (top 10 by AUC)
                  </div>
                  <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        {['Variable', 'AUC', 'KS', 'Opt Threshold', 'TP Ret%', 'FP Red%'].map(h => (
                          <th key={h} style={{ textAlign: h === 'Variable' ? 'left' : 'right',
                            color: COLORS.textDim, padding: '2px 5px', fontSize: 8 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.univariate_rankings.slice(0, 10).map((v, i) => (
                        <tr key={v.variable} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22`,
                          background: i < 3 ? COLORS.green + '08' : 'none' }}>
                          <td style={{ padding: '2px 5px', color: i < 3 ? COLORS.green : COLORS.white }}>
                            {v.variable}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', fontWeight: 'bold',
                            color: v.auc >= 0.7 ? COLORS.green : v.auc >= 0.6 ? COLORS.amber : COLORS.textMuted }}>
                            {v.auc?.toFixed(3)}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.textMuted }}>
                            {v.ks_stat?.toFixed(3)}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right', color: COLORS.white }}>
                            {v.direction === 'lower_is_tp' ? '<' : '>'}{v.optimal_threshold}
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right',
                            color: v.tp_retention >= 80 ? COLORS.green : COLORS.amber }}>
                            {v.tp_retention?.toFixed(1)}%
                          </td>
                          <td style={{ padding: '2px 5px', textAlign: 'right',
                            color: v.fp_reduction >= 30 ? COLORS.green : COLORS.textMuted }}>
                            {v.fp_reduction?.toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* RULE COMPARISON */}
              {rc && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                    RULE COMPARISON
                  </div>
                  <table style={{ fontSize: 9, borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                        {['Rule', 'Kept', 'TPs Retained', 'FPs Removed', 'COVID', 'Accuracy', 'Holdout'].map(h => (
                          <th key={h} style={{ textAlign: h === 'Rule' ? 'left' : 'right',
                            color: COLORS.textDim, padding: '3px 5px', fontSize: 8 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        { key: 'no_filter', label: 'No Filter', m: rc.no_filter, holdout: null },
                        { key: 'rule_a', label: rc.rule_a?.label || 'Rule A', m: rc.rule_a?.full_metrics, holdout: rc.rule_a?.holdout_score },
                        { key: 'rule_b', label: rc.rule_b?.label || 'Rule B', m: rc.rule_b?.full_metrics, holdout: rc.rule_b?.holdout_score },
                        { key: 'rule_c', label: rc.rule_c?.label || 'Rule C', m: rc.rule_c?.full_metrics, holdout: rc.rule_c?.holdout_score },
                      ].map(({ key, label, m, holdout }) => {
                        if (!m) return null;
                        const isWinner = key === winner;
                        return (
                          <tr key={key} style={{
                            borderBottom: `1px solid ${COLORS.cardBorder}22`,
                            background: isWinner ? COLORS.green + '11' : key === 'no_filter' ? COLORS.cyan + '08' : 'none',
                          }}>
                            <td style={{ padding: '3px 5px', color: isWinner ? COLORS.green : key === 'no_filter' ? COLORS.cyan : COLORS.white,
                              fontWeight: isWinner ? 'bold' : 'normal', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {isWinner ? '★ ' : ''}{label}
                            </td>
                            <td style={{ padding: '3px 5px', textAlign: 'right', color: COLORS.white }}>{m.signals_kept}</td>
                            <td style={{ padding: '3px 5px', textAlign: 'right', color: COLORS.green }}>
                              {m.tps_retained} ({m.tps_retained_pct}%)
                            </td>
                            <td style={{ padding: '3px 5px', textAlign: 'right', color: m.fps_removed > 0 ? COLORS.amber : COLORS.textDim }}>
                              {m.fps_removed} ({m.fps_removed_pct}%)
                            </td>
                            <td style={{ padding: '3px 5px', textAlign: 'right',
                              color: m.covid_preserved === '5/5' ? COLORS.green : COLORS.red }}>
                              {m.covid_preserved}
                            </td>
                            <td style={{ padding: '3px 5px', textAlign: 'right', fontWeight: 'bold',
                              color: m.accuracy > 70 ? COLORS.green : m.accuracy > 60 ? COLORS.amber : COLORS.red }}>
                              {m.accuracy}%
                            </td>
                            <td style={{ padding: '3px 5px', textAlign: 'right', color: COLORS.textMuted }}>
                              {holdout != null ? holdout.toFixed(3) : '—'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>

                  {/* Winner callout */}
                  {winner && rc[winner] && (
                    <div style={{ marginTop: 8, padding: '6px 12px', background: '#0a0a0a',
                      borderLeft: `3px solid ${COLORS.green}`, fontSize: 10 }}>
                      <span style={{ color: COLORS.green, fontWeight: 'bold' }}>
                        WINNING RULE: {winner.replace('_', ' ').toUpperCase()}
                      </span>
                      <span style={{ color: COLORS.textMuted, marginLeft: 8 }}>
                        {rc[winner].label}
                      </span>
                      <div style={{ color: COLORS.textDim, fontSize: 8, marginTop: 2 }}>
                        Thresholds: HY OAS pctl &lt; {rc[winner].thresholds?.x}, 3m change &lt; {rc[winner].thresholds?.y} bps
                        {' | '}Train score: {rc[winner].train_score} | Holdout score: {rc[winner].holdout_score}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* FILTER TIMELINE */}
              {data.filtered_signals && winner && data.filtered_signals[winner] && (
                <div>
                  <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>
                    FILTERED SIGNALS — {winner.replace('_', ' ').toUpperCase()} (dates where filter triggered)
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxHeight: 100, overflowY: 'auto' }}>
                    {data.filtered_signals[winner]
                      .filter(s => s.filter_triggered)
                      .map((s, i) => (
                        <span key={i} style={{ padding: '2px 6px', background: COLORS.amber + '22',
                          border: `1px solid ${COLORS.amber}44`, color: COLORS.amber, fontSize: 8, borderRadius: 2 }}>
                          {s.signal_date?.slice(0, 7)} Q{s.original_quintile}→Q3
                        </span>
                      ))}
                    {data.filtered_signals[winner].filter(s => s.filter_triggered).length === 0 && (
                      <span style={{ color: COLORS.textDim, fontSize: 9 }}>No signals filtered</span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
