import React, { useEffect, useState, useCallback } from 'react';
import { COLORS, FONT } from '../utils/theme';
import { getHealthRefresh, refreshData, clearCache } from '../utils/api';

// Polls /api/health/refresh and renders a staleness banner at the top of
// the dashboard. Four visual states (per spec):
//   fresh    — compact green indicator, minimal weight
//   aging    — amber banner, dismissible for session
//   stale    — orange banner, non-dismissible, warning copy
//   critical — red banner, non-dismissible, trading warning + diagnostics
//
// If /api/health/refresh is itself unreachable, a fail-safe amber banner
// is shown so the UI never silently appears healthy.

const SESSION_DISMISS_KEY = 'gli_healthbanner_aging_dismissed_at';
const POLL_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

function formatTimestamp(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    // Render in UTC for consistency across traders/browsers
    return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  } catch (e) {
    return iso;
  }
}

function formatAge(hoursSince) {
  if (hoursSince == null) return 'unknown';
  if (hoursSince < 1) return `${Math.round(hoursSince * 60)} minutes`;
  if (hoursSince < 24) return `${hoursSince.toFixed(1)} hours`;
  return `${(hoursSince / 24).toFixed(1)} days`;
}

function DiagnosticsModal({ health, onClose }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
          padding: '16px 20px', maxWidth: 720, width: '90%', maxHeight: '80vh',
          overflow: 'auto', fontFamily: FONT, color: COLORS.textSecondary,
        }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <span style={{ color: COLORS.amber, fontSize: 12, letterSpacing: 1, fontWeight: 'bold' }}>
            REFRESH HEALTH DIAGNOSTICS
          </span>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: `1px solid ${COLORS.cardBorder}`,
              color: COLORS.textDim, fontFamily: FONT, fontSize: 9,
              padding: '2px 8px', cursor: 'pointer',
            }}>close</button>
        </div>
        {health?.last_error && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ color: COLORS.textDim, fontSize: 9, letterSpacing: 1 }}>LAST ERROR</div>
            <div style={{ color: COLORS.red, fontSize: 10, marginTop: 2, wordBreak: 'break-word' }}>
              {health.last_error}
            </div>
          </div>
        )}
        <div style={{ marginBottom: 10 }}>
          <div style={{ color: COLORS.textDim, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>PER-MODEL STATUS</div>
          <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 4px', fontSize: 9 }}>Model</th>
                <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 4px', fontSize: 9 }}>Status</th>
                <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 4px', fontSize: 9 }}>Last success</th>
                <th style={{ textAlign: 'left', color: COLORS.textDim, padding: '2px 4px', fontSize: 9 }}>Last error</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(health?.per_model_status || {}).map(([m, s]) => (
                <tr key={m} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                  <td style={{ padding: '2px 4px', color: COLORS.white }}>{m.toUpperCase()}</td>
                  <td style={{ padding: '2px 4px',
                    color: s.status === 'success' ? COLORS.green
                      : s.status === 'failed' ? COLORS.red : COLORS.textDim }}>
                    {s.status}
                  </td>
                  <td style={{ padding: '2px 4px', color: COLORS.textMuted, fontSize: 9 }}>{formatTimestamp(s.last_success)}</td>
                  <td style={{ padding: '2px 4px', color: s.last_error ? COLORS.red : COLORS.textDim, fontSize: 9, maxWidth: 260, wordBreak: 'break-word' }}>
                    {s.last_error || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ color: COLORS.textDim, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>RAW HEALTH PAYLOAD</div>
          <pre style={{ background: '#050505', border: `1px solid ${COLORS.cardBorder}`, padding: 8,
            fontSize: 9, color: COLORS.textMuted, overflow: 'auto', margin: 0 }}>
            {JSON.stringify(health, null, 2)}
          </pre>
        </div>
        <div style={{ fontSize: 9, color: COLORS.textDim }}>
          For deeper investigation: check the server logs on Render for <code>[REFRESH]</code> and <code>[PROD]</code> lines.
        </div>
      </div>
    </div>
  );
}


export default function HealthBanner() {
  const [health, setHealth] = useState(null);
  const [fetchError, setFetchError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showDiag, setShowDiag] = useState(false);
  const [dismissedAt, setDismissedAt] = useState(() => {
    try { return window.sessionStorage.getItem(SESSION_DISMISS_KEY); } catch (e) { return null; }
  });

  const load = useCallback(async () => {
    try {
      const h = await getHealthRefresh();
      setHealth(h);
      setFetchError(null);
    } catch (e) {
      setFetchError(e?.message || 'Unable to fetch health');
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  const triggerRefresh = async () => {
    setRefreshing(true);
    try {
      clearCache();
      await refreshData();
      await load();
    } catch (e) {
      console.error(e);
    } finally {
      setRefreshing(false);
    }
  };

  const dismissAging = () => {
    const now = new Date().toISOString();
    setDismissedAt(now);
    try { window.sessionStorage.setItem(SESSION_DISMISS_KEY, now); } catch (e) {}
  };

  // Fail-safe: endpoint unreachable → fixed amber warning (spec). Cannot
  // silently show "healthy" when we don't actually know.
  if (fetchError) {
    return (
      <div style={bannerBox(COLORS.amber, false)}>
        <span style={{ fontSize: 12, fontWeight: 'bold', color: COLORS.amber }}>⚠ Unable to verify signal freshness</span>
        <span style={{ fontSize: 10, color: COLORS.textMuted, marginLeft: 8 }}>
          Health endpoint unreachable ({fetchError}). Signal freshness state is unknown.
        </span>
        <button onClick={load} style={pillBtn(COLORS.amber)}>Retry</button>
      </div>
    );
  }

  if (!health) {
    return null; // initial load
  }

  const level = health.staleness_level || 'fresh';
  const refreshStatus = health.status;
  // Treat partial as fresh-level for the banner (secondary models only;
  // primary 5F is working). Per-model dots elsewhere show the detail.
  const effectiveLevel =
    refreshStatus === 'failed' && level === 'fresh' ? 'stale' : level;

  if (effectiveLevel === 'fresh' || refreshStatus === 'partial') {
    return (
      <div style={{ padding: '4px 12px', background: COLORS.bg, border: `1px solid ${COLORS.cardBorder}`,
        marginTop: 8, marginBottom: 8, fontFamily: FONT, display: 'flex',
        alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ color: COLORS.green, fontSize: 10, fontWeight: 'bold' }}>✓ Signal current</span>
        <span style={{ color: COLORS.textMuted, fontSize: 9 }}>
          last refresh {formatAge(health.hours_since_last_success)} ago
        </span>
        {refreshStatus === 'partial' && (
          <span style={{ color: COLORS.amber, fontSize: 9 }}>
            · partial: one or more secondary models failed
          </span>
        )}
      </div>
    );
  }

  // Aging: dismissible for session
  if (effectiveLevel === 'aging' && dismissedAt) {
    return null;
  }

  const accent = effectiveLevel === 'critical' ? COLORS.red
               : effectiveLevel === 'stale' ? COLORS.orange
               : COLORS.amber;
  const title = effectiveLevel === 'critical' ? '✗ CRITICAL: Signal cannot be trusted'
              : effectiveLevel === 'stale'    ? '⚠ STALE SIGNAL'
              : '⚠ Signal aging';

  return (
    <>
      <div style={bannerBox(accent, effectiveLevel === 'critical')}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 280 }}>
            <div style={{ color: accent, fontSize: 13, fontWeight: 'bold', letterSpacing: 0.5 }}>
              {title}
            </div>
            <div style={{ color: COLORS.textSecondary, fontSize: 10, marginTop: 4 }}>
              {health.staleness_message}
              {' · '}
              <span style={{ color: COLORS.textMuted }}>
                last successful refresh: {formatTimestamp(health.last_successful_refresh)}
              </span>
            </div>
            {health.consecutive_failures > 0 && (
              <div style={{ color: COLORS.textMuted, fontSize: 10, marginTop: 2 }}>
                {health.consecutive_failures} consecutive refresh failure{health.consecutive_failures === 1 ? '' : 's'}.
                {effectiveLevel === 'critical' && ' This signal cannot be trusted for trading decisions.'}
                {effectiveLevel === 'stale' && ' Do NOT trade on this signal without manual verification of current market conditions.'}
              </div>
            )}
            {effectiveLevel === 'critical' && health.last_error && (
              <div style={{ color: COLORS.red, fontSize: 10, marginTop: 4, wordBreak: 'break-word' }}>
                Last error: {health.last_error}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap' }}>
            <button onClick={triggerRefresh} disabled={refreshing} style={pillBtn(accent)}>
              {refreshing ? '…' : 'Attempt Refresh'}
            </button>
            <button onClick={() => setShowDiag(true)} style={pillBtn(COLORS.textMuted)}>
              {effectiveLevel === 'critical' ? 'Show diagnostics' : 'View Diagnostics'}
            </button>
            {effectiveLevel === 'aging' && (
              <button onClick={dismissAging} style={pillBtn(COLORS.textMuted)}>dismiss</button>
            )}
          </div>
        </div>
      </div>
      {showDiag && <DiagnosticsModal health={health} onClose={() => setShowDiag(false)} />}
    </>
  );
}


// ── Small per-model status indicator (used in the hero header) ──────
export function ModelStatusDots({ health }) {
  if (!health || !health.per_model_status) return null;
  const order = ['5f', '4f', '3fa', '3fa_eq', '2f'];
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      {order.filter(m => m in health.per_model_status).map(m => {
        const s = health.per_model_status[m];
        const sym = s.status === 'success' ? '✓' : s.status === 'failed' ? '✗' : '?';
        const color = s.status === 'success' ? COLORS.green
                    : s.status === 'failed' ? COLORS.red
                    : COLORS.textDim;
        const tip = s.status === 'failed'
          ? `${m.toUpperCase()}: ${s.last_error || 'failed'}`
          : `${m.toUpperCase()}: last success ${s.last_success || 'never'}`;
        return (
          <span key={m} title={tip} style={{ color, fontSize: 8, letterSpacing: 0.5 }}>
            {m.toUpperCase()} <span style={{ fontWeight: 'bold' }}>{sym}</span>
          </span>
        );
      })}
    </span>
  );
}


// ── Styling helpers ──────────────────────────────────────────────────
function bannerBox(accentColor, heavy) {
  return {
    padding: heavy ? '12px 16px' : '10px 14px',
    background: heavy ? '#1a0505' : '#0d0d0d',
    border: `1px solid ${accentColor}`,
    borderLeft: `4px solid ${accentColor}`,
    marginTop: 8,
    marginBottom: 8,
    fontFamily: FONT,
  };
}

function pillBtn(color) {
  return {
    padding: '2px 10px',
    background: 'none',
    color,
    border: `1px solid ${color}66`,
    fontFamily: FONT,
    fontSize: 9,
    cursor: 'pointer',
  };
}
