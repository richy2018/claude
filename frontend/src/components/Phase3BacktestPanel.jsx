import React, { useState, useEffect } from 'react';
import { COLORS, FONT } from '../utils/theme';
import { runPhase3Backtest, getPhase3Backtest } from '../utils/api';

const S = {
  label: { color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 },
  table: { fontSize: 9, borderCollapse: 'collapse', width: '100%' },
  th: { color: COLORS.textDim, padding: '3px 5px', fontSize: 8, borderBottom: `1px solid ${COLORS.cardBorder}` },
  td: { padding: '3px 5px', fontSize: 9 },
  section: { marginBottom: 12 },
};

function MetricCell({ value, suffix = '', good = 'high', threshold = 0 }) {
  if (value == null) return <td style={{ ...S.td, textAlign: 'right', color: COLORS.textDim }}>—</td>;
  const isGood = good === 'high' ? value > threshold : value < threshold;
  return (
    <td style={{ ...S.td, textAlign: 'right', color: isGood ? COLORS.green : COLORS.textMuted }}>
      {typeof value === 'number' ? value.toFixed(2) : value}{suffix}
    </td>
  );
}

function DeltaBadge({ delta }) {
  if (!delta) return null;
  const { value, direction } = delta;
  const color = direction === 'better' ? COLORS.green : direction === 'worse' ? COLORS.red : COLORS.textDim;
  return (
    <span style={{ color, fontSize: 8, marginLeft: 3 }}>
      {value > 0 ? '+' : ''}{value.toFixed(2)}
    </span>
  );
}

function CriterionBadge({ result }) {
  const color = result === 'pass' ? COLORS.green : result === 'marginal' ? COLORS.amber : COLORS.red;
  return (
    <span style={{ color, fontSize: 8, fontWeight: 'bold', padding: '1px 5px',
      border: `1px solid ${color}44`, borderRadius: 2 }}>
      {result.toUpperCase()}
    </span>
  );
}

export default function Phase3BacktestPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showDetail, setShowDetail] = useState(null); // which detail section to expand

  useEffect(() => {
    getPhase3Backtest().then(r => {
      if (r && !r.error) setData(r);
    }).catch(() => {});
  }, []);

  const run = async () => {
    setLoading(true);
    try {
      const r = await runPhase3Backtest(true);
      if (r && !r.error) setData(r);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const metrics = data?.metrics;
  const rec = data?.recommendation;
  const variants = ['no_filter', 'rule_a', 'rule_b', 'rule_c', 'buyhold'];
  const variantLabels = {
    no_filter: 'No Filter', rule_a: 'Rule A', rule_b: 'Rule B',
    rule_c: 'Rule C', buyhold: 'SPY B&H',
  };

  return (
    <div style={{ marginTop: 12 }}>
      <button onClick={() => setExpanded(!expanded)} style={{
        background: 'none', border: `1px solid ${COLORS.cardBorder}`, color: COLORS.textMuted,
        fontFamily: FONT, fontSize: 10, padding: '4px 14px', cursor: 'pointer', width: '100%', textAlign: 'left',
      }}>
        {expanded ? '\u25BE' : '\u25B8'} Phase 3 — Filtered Signal Backtest
      </button>
      {expanded && (
        <div style={{ padding: '12px 16px', background: COLORS.bgDark, border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <span style={{ color: COLORS.amber, fontSize: 11, letterSpacing: 1 }}>PHASE 3 — FILTERED SIGNAL BACKTEST</span>
            <button onClick={run} disabled={loading}
              style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              {loading ? 'RUNNING (~30s)...' : data ? 'RE-RUN' : 'RUN BACKTEST'}
            </button>
            {data?.summary?.from_cache && (
              <span style={{ color: COLORS.amber, fontSize: 8 }}>(cached)</span>
            )}
            {data?.summary && (
              <span style={{ color: COLORS.textDim, fontSize: 8 }}>
                {data.summary.n_months} months | {data.summary.date_range?.[0]?.slice(0,7)} to {data.summary.date_range?.[1]?.slice(0,7)}
              </span>
            )}
          </div>

          {!data && !loading && (
            <div style={{ color: COLORS.textDim, fontSize: 9 }}>
              Requires Phase 2 data. Run Phase 2 first, then click RUN BACKTEST.
            </div>
          )}

          {data && (
            <>
              {/* RECOMMENDATION BANNER */}
              {rec && (
                <div style={{ ...S.section, padding: '8px 12px', background: '#0a0a0a',
                  borderLeft: `3px solid ${rec.confidence === 'high' ? COLORS.green : rec.confidence === 'moderate' ? COLORS.amber : COLORS.red}` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: COLORS.green, fontWeight: 'bold', fontSize: 10 }}>
                      RECOMMENDATION: {(rec.recommended_rule || '').replace('_', ' ').toUpperCase()}
                    </span>
                    <span style={{ color: COLORS.textMuted, fontSize: 8, padding: '1px 6px',
                      border: `1px solid ${COLORS.cardBorder}`, borderRadius: 2 }}>
                      {rec.confidence} confidence
                    </span>
                  </div>
                  <div style={{ color: COLORS.textDim, fontSize: 8, marginTop: 3, lineHeight: 1.4 }}>
                    {rec.reasoning}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                    {(rec.criteria || []).map((c, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                        <CriterionBadge result={c.result} />
                        <span style={{ color: COLORS.textDim, fontSize: 7 }}>{c.name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* PERFORMANCE METRICS TABLE */}
              {metrics && (
                <div style={S.section}>
                  <div style={S.label}>PERFORMANCE METRICS</div>
                  <table style={S.table}>
                    <thead>
                      <tr>
                        {['Variant', 'Total Ret', 'Ann Ret', 'Ann Vol', 'Sharpe', 'Sortino', 'Max DD', 'Calmar'].map(h => (
                          <th key={h} style={{ ...S.th, textAlign: h === 'Variant' ? 'left' : 'right' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {variants.map(v => {
                        const m = metrics[v];
                        if (!m) return null;
                        const isBest = v === data.summary?.best_backtest_variant;
                        const isBH = v === 'buyhold';
                        return (
                          <tr key={v} style={{
                            borderBottom: `1px solid ${COLORS.cardBorder}22`,
                            background: isBest ? COLORS.green + '0a' : isBH ? COLORS.cyan + '06' : 'none',
                          }}>
                            <td style={{ ...S.td, color: isBest ? COLORS.green : isBH ? COLORS.cyan : COLORS.white,
                              fontWeight: isBest ? 'bold' : 'normal' }}>
                              {isBest ? '\u2605 ' : ''}{variantLabels[v] || v}
                            </td>
                            <MetricCell value={m.total_return} suffix="%" />
                            <MetricCell value={m.annualized_return} suffix="%" />
                            <td style={{ ...S.td, textAlign: 'right', color: COLORS.textMuted }}>{m.annualized_vol?.toFixed(2)}%</td>
                            <MetricCell value={m.sharpe} threshold={0.5} />
                            <MetricCell value={m.sortino} threshold={0.7} />
                            <td style={{ ...S.td, textAlign: 'right',
                              color: m.max_drawdown > -20 ? COLORS.green : m.max_drawdown > -35 ? COLORS.amber : COLORS.red }}>
                              {m.max_drawdown?.toFixed(1)}%
                            </td>
                            <MetricCell value={m.calmar} threshold={0.3} />
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* DELTAS */}
              {data.deltas && (
                <div style={S.section}>
                  <div style={S.label}>DELTAS vs NO FILTER</div>
                  <table style={S.table}>
                    <thead>
                      <tr>
                        {['Rule', 'Ann Ret \u0394', 'Sharpe \u0394', 'Sortino \u0394', 'Max DD \u0394', 'Calmar \u0394'].map(h => (
                          <th key={h} style={{ ...S.th, textAlign: h.startsWith('Rule') ? 'left' : 'right' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {['rule_a', 'rule_b', 'rule_c'].map(rule => {
                        const d = data.deltas[`${rule}_vs_no_filter`];
                        if (!d) return null;
                        return (
                          <tr key={rule} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                            <td style={S.td}>{variantLabels[rule]}</td>
                            {['annualized_return', 'sharpe', 'sortino', 'max_drawdown', 'calmar'].map(m => (
                              <td key={m} style={{ ...S.td, textAlign: 'right' }}>
                                <DeltaBadge delta={d[m]} />
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* SUBPERIOD SHARPE RATIOS */}
              {data.subperiod_sharpes && (
                <div style={S.section}>
                  <div style={S.label}>SUBPERIOD SHARPE RATIOS</div>
                  <table style={S.table}>
                    <thead>
                      <tr>
                        <th style={{ ...S.th, textAlign: 'left' }}>Period</th>
                        {variants.map(v => (
                          <th key={v} style={{ ...S.th, textAlign: 'right' }}>{variantLabels[v]}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(data.subperiod_sharpes).map(([period, sharpes]) => (
                        <tr key={period} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                          <td style={{ ...S.td, color: COLORS.white }}>{period}</td>
                          {variants.map(v => (
                            <td key={v} style={{ ...S.td, textAlign: 'right',
                              color: sharpes[v] != null && sharpes[v] > 0.5 ? COLORS.green :
                                     sharpes[v] != null && sharpes[v] > 0 ? COLORS.textMuted : COLORS.red }}>
                              {sharpes[v] != null ? sharpes[v].toFixed(3) : '\u2014'}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* EXPANDABLE DETAIL SECTIONS */}
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {['alpha', 'crashes', 'drawdowns', 'mc', 'triggers'].map(key => (
                  <button key={key} onClick={() => setShowDetail(showDetail === key ? null : key)}
                    style={{ padding: '2px 8px', background: showDetail === key ? COLORS.cyan + '22' : 'none',
                      color: showDetail === key ? COLORS.cyan : COLORS.textMuted,
                      border: `1px solid ${showDetail === key ? COLORS.cyan + '44' : COLORS.cardBorder}`,
                      fontFamily: FONT, fontSize: 8, cursor: 'pointer' }}>
                    {{ alpha: 'CAPM Alpha', crashes: 'Crash Episodes', drawdowns: 'Drawdowns',
                       mc: 'Monte Carlo', triggers: 'Filter Triggers' }[key]}
                  </button>
                ))}
              </div>

              {/* ALPHA DECOMPOSITION */}
              {showDetail === 'alpha' && data.alpha_decomp && (
                <div style={S.section}>
                  <div style={S.label}>CAPM ALPHA DECOMPOSITION</div>
                  <table style={S.table}>
                    <thead>
                      <tr>
                        {['Variant', 'Alpha (ann%)', 'Beta', 'R\u00B2', 't-stat', 'Significant'].map(h => (
                          <th key={h} style={{ ...S.th, textAlign: h === 'Variant' ? 'left' : 'right' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {['no_filter', 'rule_a', 'rule_b', 'rule_c'].map(v => {
                        const a = data.alpha_decomp[v];
                        if (!a) return null;
                        return (
                          <tr key={v} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                            <td style={S.td}>{variantLabels[v]}</td>
                            <td style={{ ...S.td, textAlign: 'right', fontWeight: 'bold',
                              color: a.alpha_annual_pct > 0 ? COLORS.green : COLORS.red }}>
                              {a.alpha_annual_pct > 0 ? '+' : ''}{a.alpha_annual_pct?.toFixed(2)}%
                            </td>
                            <td style={{ ...S.td, textAlign: 'right', color: COLORS.textMuted }}>{a.beta?.toFixed(3)}</td>
                            <td style={{ ...S.td, textAlign: 'right', color: COLORS.textMuted }}>{a.r_squared?.toFixed(3)}</td>
                            <td style={{ ...S.td, textAlign: 'right', color: COLORS.textMuted }}>{a.t_stat?.toFixed(2)}</td>
                            <td style={{ ...S.td, textAlign: 'right',
                              color: a.significant ? COLORS.green : COLORS.textDim }}>
                              {a.significant ? 'YES' : 'no'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* CRASH EPISODES */}
              {showDetail === 'crashes' && data.crash_detection && (
                <div style={S.section}>
                  <div style={S.label}>CRASH EPISODES (SPY drawdown &gt; 15%)</div>
                  {data.crash_detection.length === 0 ? (
                    <div style={{ color: COLORS.textDim, fontSize: 9 }}>No crash episodes detected in sample period.</div>
                  ) : (
                    <table style={S.table}>
                      <thead>
                        <tr>
                          {['Period', 'SPY DD', 'No Filter', 'Rule A', 'Rule B', 'Rule C', 'Duration'].map(h => (
                            <th key={h} style={{ ...S.th, textAlign: h === 'Period' ? 'left' : 'right' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.crash_detection.map((ep, i) => (
                          <tr key={i} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                            <td style={{ ...S.td, color: COLORS.white }}>
                              {ep.start?.slice(0,7)} to {ep.end?.slice(0,7) || 'ongoing'}
                            </td>
                            <td style={{ ...S.td, textAlign: 'right', color: COLORS.red, fontWeight: 'bold' }}>
                              {ep.depth_pct?.toFixed(1)}%
                            </td>
                            {['no_filter', 'rule_a', 'rule_b', 'rule_c'].map(v => (
                              <td key={v} style={{ ...S.td, textAlign: 'right',
                                color: (ep.variant_drawdowns?.[v] || 0) > ep.depth_pct ? COLORS.green : COLORS.textMuted }}>
                                {ep.variant_drawdowns?.[v]?.toFixed(1) ?? '\u2014'}%
                              </td>
                            ))}
                            <td style={{ ...S.td, textAlign: 'right', color: COLORS.textDim }}>
                              {ep.duration_months}m
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* DRAWDOWNS */}
              {showDetail === 'drawdowns' && data.drawdowns && (
                <div style={S.section}>
                  <div style={S.label}>TOP DRAWDOWNS BY VARIANT</div>
                  {['no_filter', 'rule_a', 'rule_b', 'rule_c'].map(v => {
                    const dd = data.drawdowns[v];
                    if (!dd) return null;
                    return (
                      <div key={v} style={{ marginBottom: 8 }}>
                        <div style={{ color: COLORS.textMuted, fontSize: 8, marginBottom: 2 }}>
                          {variantLabels[v]} — Current DD: {dd.current_drawdown?.toFixed(1)}%
                        </div>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {(dd.worst_drawdowns || []).slice(0, 3).map((d, i) => (
                            <span key={i} style={{ padding: '2px 6px', fontSize: 8,
                              background: COLORS.red + '11', border: `1px solid ${COLORS.red}33`, borderRadius: 2 }}>
                              <span style={{ color: COLORS.red }}>{d.depth_pct?.toFixed(1)}%</span>
                              <span style={{ color: COLORS.textDim, marginLeft: 4 }}>
                                {d.start?.slice(0,7)} ({d.duration_months}m)
                              </span>
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* MONTE CARLO */}
              {showDetail === 'mc' && data.monte_carlo && (
                <div style={S.section}>
                  <div style={S.label}>MONTE CARLO ({data.monte_carlo.n_permutations?.toLocaleString()} permutations)</div>
                  <table style={S.table}>
                    <thead>
                      <tr>
                        {['Variant', 'Actual Sharpe', 'Perm Mean', 'Perm 95th', 'p-value', 'Significant'].map(h => (
                          <th key={h} style={{ ...S.th, textAlign: h === 'Variant' ? 'left' : 'right' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {['no_filter', 'rule_a', 'rule_b', 'rule_c'].map(v => {
                        const mc = data.monte_carlo.variants?.[v];
                        if (!mc) return null;
                        return (
                          <tr key={v} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                            <td style={S.td}>{variantLabels[v]}</td>
                            <td style={{ ...S.td, textAlign: 'right', fontWeight: 'bold' }}>{mc.actual_sharpe?.toFixed(3)}</td>
                            <td style={{ ...S.td, textAlign: 'right', color: COLORS.textMuted }}>{mc.permuted_mean?.toFixed(3)}</td>
                            <td style={{ ...S.td, textAlign: 'right', color: COLORS.textMuted }}>{mc.percentile_95?.toFixed(3)}</td>
                            <td style={{ ...S.td, textAlign: 'right', fontWeight: 'bold',
                              color: mc.p_value < 0.05 ? COLORS.green : mc.p_value < 0.15 ? COLORS.amber : COLORS.textDim }}>
                              {mc.p_value?.toFixed(4)}
                            </td>
                            <td style={{ ...S.td, textAlign: 'right',
                              color: mc.significant ? COLORS.green : COLORS.textDim }}>
                              {mc.significant ? 'YES' : 'no'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {data.monte_carlo.delta_tests && Object.keys(data.monte_carlo.delta_tests).length > 0 && (
                    <div style={{ marginTop: 6 }}>
                      <div style={{ color: COLORS.textDim, fontSize: 8, marginBottom: 3 }}>DELTA SIGNIFICANCE (filter improvement vs random)</div>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {Object.entries(data.monte_carlo.delta_tests).map(([k, dt]) => (
                          <span key={k} style={{ fontSize: 8, color: dt.significant ? COLORS.green : COLORS.textDim }}>
                            {k.replace('_vs_no_filter', '').replace('_', ' ').toUpperCase()}: {'\u0394'}={dt.actual_delta?.toFixed(4)}, p={dt.p_value?.toFixed(3)}
                            {dt.significant ? ' *' : ''}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* FILTER TRIGGERS */}
              {showDetail === 'triggers' && (
                <div style={S.section}>
                  <div style={S.label}>FILTER TRIGGER ANALYSIS</div>
                  {['rule_a', 'rule_b', 'rule_c'].map(rule => {
                    const triggers = data[`${rule}_filter_triggers`];
                    if (!triggers || triggers.length === 0) return null;
                    const nCorrect = triggers.filter(t => t.was_correct).length;
                    const nAssessed = triggers.filter(t => t.was_correct != null).length;
                    const accuracy = nAssessed > 0 ? (nCorrect / nAssessed * 100).toFixed(0) : 0;
                    return (
                      <div key={rule} style={{ marginBottom: 8 }}>
                        <div style={{ color: COLORS.textMuted, fontSize: 8, marginBottom: 3 }}>
                          {variantLabels[rule]} — {triggers.length} triggers, {accuracy}% correct ({nCorrect}/{nAssessed})
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, maxHeight: 80, overflowY: 'auto' }}>
                          {triggers.map((t, i) => (
                            <span key={i} style={{ padding: '1px 5px', fontSize: 7,
                              background: t.was_correct ? COLORS.green + '11' : COLORS.red + '11',
                              border: `1px solid ${t.was_correct ? COLORS.green : COLORS.red}33`,
                              color: t.was_correct ? COLORS.green : COLORS.red, borderRadius: 2 }}>
                              {t.date?.slice(0, 7)} Q{t.original_quintile}{'\u2192'}Q3
                              {t.fwd_3m_spy_return != null && (
                                <span style={{ color: COLORS.textDim, marginLeft: 3 }}>
                                  3m:{t.fwd_3m_spy_return > 0 ? '+' : ''}{t.fwd_3m_spy_return}%
                                </span>
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
