import React, { useState, useCallback, useEffect, useRef } from 'react';
import { COLORS, FONT, REGIME_COLORS, REGIME_LABELS } from './utils/theme';
import HeaderBar from './components/HeaderBar';
import NavBar from './components/NavBar';
import CrossAssetRegimes from './components/CrossAssetRegimes';
import STIRPanel from './components/STIRPanel';
import FairValuePanel from './components/FairValuePanel';
import EquitiesPanel from './components/EquitiesPanel';
import YieldCurvePanel from './components/YieldCurvePanel';
import RiskPremiaPanel from './components/RiskPremiaPanel';
import TICHoldingsPanel from './components/TICHoldingsPanel';
import PortfolioBondScreener from './components/PortfolioBondScreener';
import { refreshData } from './utils/api';

const PLACEHOLDER_TABS = ['NEWS', 'BRIEFING'];
const TAB_ORDER = ['DASHBOARD', 'REGIME MAP', 'CROSS-ASSET', 'EQUITIES', 'LIQUIDITY', 'PORTFOLIO', 'NEWS', 'BRIEFING'];
const AUTO_REFRESH_INTERVALS = [0, 900000, 1800000, 3600000]; // manual, 15m, 30m, 1h
const INTERVAL_LABELS = ['MANUAL', '15 MIN', '30 MIN', '1 HOUR'];

export default function App() {
  const [activeTab, setActiveTab] = useState('CROSS-ASSET');
  const [isLoading, setIsLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [fredKey, setFredKey] = useState('');
  const [showSetup, setShowSetup] = useState(false);
  const [refreshError, setRefreshError] = useState(null);
  const [refreshResult, setRefreshResult] = useState(null);
  const [autoRefreshIdx, setAutoRefreshIdx] = useState(0);
  const [showRegimes, setShowRegimes] = useState(false);
  const autoRefreshTimer = useRef(null);

  const handleRefresh = useCallback(async () => {
    if (!fredKey) {
      setShowSetup(true);
      return;
    }
    setIsLoading(true);
    setRefreshError(null);
    try {
      const result = await refreshData(fredKey);
      setLastRefresh(result.last_refresh);
      setRefreshResult(result);
      setShowSetup(false);
    } catch (e) {
      setRefreshError(e.message);
    } finally {
      setIsLoading(false);
    }
  }, [fredKey]);

  // Auto-refresh
  useEffect(() => {
    if (autoRefreshTimer.current) clearInterval(autoRefreshTimer.current);
    const interval = AUTO_REFRESH_INTERVALS[autoRefreshIdx];
    if (interval > 0 && fredKey) {
      autoRefreshTimer.current = setInterval(() => {
        handleRefresh();
      }, interval);
    }
    return () => { if (autoRefreshTimer.current) clearInterval(autoRefreshTimer.current); };
  }, [autoRefreshIdx, fredKey, handleRefresh]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      // Don't capture when typing in inputs
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      switch (e.key.toLowerCase()) {
        case 'r':
          if (!e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            if (fredKey) handleRefresh();
            else setShowSetup(true);
          }
          break;
        case '1': e.preventDefault(); setActiveTab('DASHBOARD'); break;
        case '2': e.preventDefault(); setActiveTab('REGIME MAP'); break;
        case '3': e.preventDefault(); setActiveTab('CROSS-ASSET'); break;
        case '4': e.preventDefault(); setActiveTab('EQUITIES'); break;
        case '5': e.preventDefault(); setActiveTab('NEWS'); break;
        case '6': e.preventDefault(); setActiveTab('BRIEFING'); break;
        case 'escape':
          if (showSetup) { e.preventDefault(); setShowSetup(false); }
          break;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [fredKey, handleRefresh, showSetup]);

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: COLORS.bg,
      fontFamily: FONT,
      color: COLORS.white,
    }}>
      <HeaderBar
        onRefresh={() => {
          if (!fredKey) setShowSetup(true);
          else handleRefresh();
        }}
        isLoading={isLoading}
        lastRefresh={lastRefresh}
        onShowRegimes={() => setShowRegimes(true)}
      />
      <NavBar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Regime legend modal */}
      {showRegimes && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.85)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowRegimes(false); }}
        >
          <div style={{
            backgroundColor: '#111',
            border: `1px solid ${COLORS.cyan}44`,
            padding: 28, width: 520, fontFamily: FONT,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ color: COLORS.amber, fontSize: 14, letterSpacing: '0.08em', margin: 0 }}>
                REGIME DEFINITIONS
              </h3>
              <button onClick={() => setShowRegimes(false)} style={{
                background: 'none', border: 'none', color: COLORS.textMuted, fontSize: 18, cursor: 'pointer',
              }}>×</button>
            </div>
            <div style={{ color: COLORS.textMuted, fontSize: 10, marginBottom: 12, lineHeight: 1.5 }}>
              Cross-asset regimes are classified by the direction of three assets over a rolling lookback window:
              S&P 500 (SPX), 10-Year Treasury Yield (10Y), and US Dollar Index (DXY).
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: FONT }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  {['REGIME', 'SPX', 'RATES', 'DOLLAR'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', color: COLORS.textMuted, fontSize: 10, textAlign: 'left', fontWeight: 'normal' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(REGIME_LABELS).map(([key, label]) => {
                  const parts = label.split(' / ');
                  return (
                    <tr key={key} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                      <td style={{ padding: '6px 8px', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: REGIME_COLORS[key] }} />
                        <span style={{ color: REGIME_COLORS[key], fontWeight: 'bold' }}>{key}</span>
                        <span style={{ color: COLORS.textSecondary, fontSize: 11 }}>{label}</span>
                      </td>
                      <td style={{ padding: '6px 8px', color: parts[0]?.includes('Up') ? COLORS.green : COLORS.red, fontSize: 11 }}>
                        {parts[0]?.includes('Up') ? '▲' : '▼'}
                      </td>
                      <td style={{ padding: '6px 8px', color: parts[1]?.includes('Up') ? COLORS.green : COLORS.red, fontSize: 11 }}>
                        {parts[1]?.includes('Up') ? '▲' : '▼'}
                      </td>
                      <td style={{ padding: '6px 8px', color: parts[2]?.includes('Up') ? COLORS.green : COLORS.red, fontSize: 11 }}>
                        {parts[2]?.includes('Up') ? '▲' : '▼'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div style={{ marginTop: 12, fontSize: 9, color: COLORS.textMuted, lineHeight: 1.5 }}>
              ▲ = Up (green) &nbsp; ▼ = Down (red) &nbsp; | &nbsp; Press Esc or click outside to close.
            </div>
          </div>
        </div>
      )}

      {/* Setup modal */}
      {showSetup && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.85)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowSetup(false); }}
        >
          <div style={{
            backgroundColor: '#111',
            border: `1px solid ${COLORS.amber}44`,
            padding: 32, width: 500, fontFamily: FONT,
          }}>
            <h3 style={{ color: COLORS.amber, fontSize: 14, marginBottom: 16, letterSpacing: '0.08em' }}>
              DATA SOURCE CONFIGURATION
            </h3>
            <label style={{ display: 'block', color: COLORS.textMuted, fontSize: 11, marginBottom: 6, letterSpacing: '0.05em' }}>
              FRED API KEY
            </label>
            <input
              type="text"
              value={fredKey}
              onChange={(e) => setFredKey(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && fredKey) handleRefresh(); }}
              placeholder="Enter your FRED API key..."
              autoFocus
              style={{
                width: '100%', padding: '8px 12px',
                backgroundColor: '#0a0a0a', border: `1px solid ${COLORS.cardBorder}`,
                color: COLORS.white, fontFamily: FONT, fontSize: 12, outline: 'none',
                marginBottom: 16,
              }}
            />
            <div style={{ color: COLORS.textMuted, fontSize: 10, marginBottom: 16 }}>
              Get a free API key from{' '}
              <span style={{ color: COLORS.cyan }}>https://fred.stlouisfed.org/docs/api/api_key.html</span>
            </div>

            {/* Auto-refresh setting */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', color: COLORS.textMuted, fontSize: 11, marginBottom: 6, letterSpacing: '0.05em' }}>
                AUTO-REFRESH INTERVAL
              </label>
              <div style={{ display: 'flex', gap: 6 }}>
                {INTERVAL_LABELS.map((label, i) => (
                  <button key={label} onClick={() => setAutoRefreshIdx(i)} style={{
                    padding: '4px 12px',
                    backgroundColor: autoRefreshIdx === i ? COLORS.amber : '#1a1a1a',
                    color: autoRefreshIdx === i ? '#0a0a0a' : '#888',
                    border: `1px solid ${autoRefreshIdx === i ? COLORS.amber : '#333'}`,
                    fontFamily: FONT, fontSize: 10, cursor: 'pointer',
                  }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {refreshError && (
              <div style={{ color: COLORS.red, fontSize: 11, marginBottom: 12 }}>
                Error: {refreshError}
              </div>
            )}
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={handleRefresh}
                disabled={!fredKey || isLoading}
                style={{
                  padding: '8px 20px',
                  backgroundColor: fredKey ? COLORS.amber : '#333',
                  color: fredKey ? '#000' : '#666',
                  border: 'none', fontFamily: FONT, fontSize: 12,
                  letterSpacing: '0.05em',
                  cursor: fredKey ? 'pointer' : 'not-allowed',
                }}
              >
                {isLoading ? 'LOADING...' : 'FETCH DATA'}
              </button>
              <button
                onClick={() => setShowSetup(false)}
                style={{
                  padding: '8px 20px',
                  backgroundColor: 'transparent', color: COLORS.textMuted,
                  border: `1px solid ${COLORS.cardBorder}`,
                  fontFamily: FONT, fontSize: 12,
                }}
              >
                CANCEL
              </button>
            </div>
            {refreshResult && (
              <div style={{ marginTop: 16, fontSize: 11, color: COLORS.green }}>
                Data loaded: {refreshResult.fred_series_count} FRED series, {refreshResult.yahoo_series_count} Yahoo tickers
                {refreshResult.errors && Object.keys(refreshResult.errors).length > 0 && (
                  <span style={{ color: COLORS.amber }}> (some errors — check console)</span>
                )}
              </div>
            )}
            <div style={{ marginTop: 16, fontSize: 10, color: COLORS.textMuted, lineHeight: 1.5 }}>
              Keyboard shortcuts: R = refresh | 1-6 = switch tabs | Esc = close
            </div>
          </div>
        </div>
      )}

      {/* Main content */}
      <div style={{ padding: '0 16px 16px 16px' }}>
        {activeTab === 'DASHBOARD' && <DashboardTab />}
        {activeTab === 'REGIME MAP' && <RegimeMapTab />}
        {activeTab === 'CROSS-ASSET' && <CrossAssetRegimes />}
        {activeTab === 'EQUITIES' && <EquitiesPanel />}
        {activeTab === 'LIQUIDITY' && <LiquidityTab />}
        {activeTab === 'PORTFOLIO' && <PortfolioTab />}
        {PLACEHOLDER_TABS.includes(activeTab) && (
          <PlaceholderPanel title={activeTab} subtitle="Coming soon" />
        )}
      </div>
    </div>
  );
}

function DashboardTab() {
  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div style={{
          backgroundColor: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
          padding: 16, minHeight: 400,
        }}>
          <STIRPanel />
        </div>
        <div style={{
          backgroundColor: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
          padding: 16, minHeight: 400, overflowY: 'auto',
        }}>
          <FairValuePanel />
        </div>
      </div>
    </div>
  );
}

const REGIME_MAP_TABS = ['YIELD CURVE', 'RISK PREMIA'];

const LIQUIDITY_TABS = ['FOREIGN HOLDERS', 'GLOBAL NET LIQUIDITY', 'LIQUIDITY DRIVERS', 'US FUNDING', 'DOLLAR STRESS', 'CREDIT & COLLATERAL'];

function LiquidityTab() {
  const [subTab, setSubTab] = useState('FOREIGN HOLDERS');
  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{
        display: 'flex', gap: 0,
        borderBottom: `1px solid ${COLORS.cardBorder}`, marginBottom: 8,
      }}>
        {LIQUIDITY_TABS.map(tab => (
          <button key={tab} onClick={() => setSubTab(tab)} style={{
            background: 'none', border: 'none',
            borderBottom: subTab === tab ? `2px solid ${COLORS.amber}` : '2px solid transparent',
            color: subTab === tab ? COLORS.amber : COLORS.textMuted,
            fontFamily: FONT, fontSize: 13, letterSpacing: 1,
            padding: '8px 16px', cursor: tab === 'FOREIGN HOLDERS' ? 'pointer' : 'default',
            opacity: tab === 'FOREIGN HOLDERS' ? 1 : 0.4,
          }}>{tab}</button>
        ))}
      </div>
      {subTab === 'FOREIGN HOLDERS' && <TICHoldingsPanel />}
      {subTab !== 'FOREIGN HOLDERS' && (
        <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontSize: 13 }}>
          <div style={{ fontSize: 18, color: COLORS.amber, letterSpacing: 2, marginBottom: 12 }}>{subTab}</div>
          <div>Coming soon</div>
        </div>
      )}
    </div>
  );
}

const PORTFOLIO_TABS = ['SCREENER', 'PORTFOLIO', 'SCENARIOS', 'SUMMARY', 'SETTINGS'];

function PortfolioTab() {
  const [subTab, setSubTab] = useState('SCREENER');
  // Shared state across sub-tabs
  const [portfolio, setPortfolio] = useState([]);  // array of {bond/equity, allocation}
  const [clientSettings, setClientSettings] = useState({
    clientName: '', investmentAmount: 200000, targetReturn: 5.5,
    riskTolerance: 'Moderate',
    fees: { management: 0.5, performance: 0, formation: 0.1, custody: 0.2, trading: 0.2 },
  });

  const addToPortfolio = (item) => {
    setPortfolio(prev => {
      if (prev.find(p => p.id === item.id)) return prev;
      return [...prev, { ...item, allocation: 10000 }];
    });
  };

  const removeFromPortfolio = (id) => {
    setPortfolio(prev => prev.filter(p => p.id !== id));
  };

  const updateAllocation = (id, amount) => {
    setPortfolio(prev => prev.map(p => p.id === id ? { ...p, allocation: amount } : p));
  };

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{
        display: 'flex', gap: 0,
        borderBottom: `1px solid ${COLORS.cardBorder}`, marginBottom: 8,
      }}>
        {PORTFOLIO_TABS.map(tab => (
          <button key={tab} onClick={() => setSubTab(tab)} style={{
            background: 'none', border: 'none',
            borderBottom: subTab === tab ? `2px solid ${COLORS.amber}` : '2px solid transparent',
            color: subTab === tab ? COLORS.amber : COLORS.textMuted,
            fontFamily: FONT, fontSize: 13, letterSpacing: 1,
            padding: '8px 20px', cursor: 'pointer',
          }}>{tab}
            {tab === 'PORTFOLIO' && portfolio.length > 0 && (
              <span style={{ marginLeft: 6, fontSize: 10, color: COLORS.green }}>({portfolio.length})</span>
            )}
          </button>
        ))}
      </div>
      {subTab === 'SCREENER' && (
        <PortfolioBondScreener onAddToPortfolio={addToPortfolio} portfolio={portfolio} />
      )}
      {subTab !== 'SCREENER' && (
        <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontSize: 13 }}>
          <div style={{ fontSize: 18, color: COLORS.amber, letterSpacing: 2, marginBottom: 12 }}>{subTab}</div>
          <div>Coming in next phase</div>
        </div>
      )}
    </div>
  );
}

function RegimeMapTab() {
  const [subTab, setSubTab] = useState('YIELD CURVE');
  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{
        display: 'flex', gap: 0,
        borderBottom: `1px solid ${COLORS.cardBorder}`, marginBottom: 8,
      }}>
        {REGIME_MAP_TABS.map(tab => (
          <button key={tab} onClick={() => setSubTab(tab)} style={{
            background: 'none', border: 'none',
            borderBottom: subTab === tab ? `2px solid ${COLORS.amber}` : '2px solid transparent',
            color: subTab === tab ? COLORS.amber : COLORS.textMuted,
            fontFamily: FONT, fontSize: 13, letterSpacing: 1,
            padding: '8px 20px', cursor: 'pointer',
          }}>{tab}</button>
        ))}
      </div>
      {subTab === 'YIELD CURVE' && <YieldCurvePanel />}
      {subTab === 'RISK PREMIA' && <RiskPremiaPanel />}
    </div>
  );
}

function PlaceholderPanel({ title, subtitle }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      minHeight: 400, color: COLORS.textMuted,
    }}>
      <div style={{ fontSize: 24, color: COLORS.amber, letterSpacing: '0.1em', marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 12 }}>{subtitle}</div>
    </div>
  );
}
