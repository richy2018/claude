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
import USFundingPanel from './components/USFundingPanel';
import GlobalNetLiquidityPanel from './components/GlobalNetLiquidityPanel';
import LiquidityDriversPanel from './components/LiquidityDriversPanel';
import DollarStressPanel from './components/DollarStressPanel';
import LiquidityCompositePanel from './components/LiquidityCompositePanel';
import DollarFundingPanel from './components/DollarFundingPanel';
import CreditSpreadsPanel from './components/CreditSpreadsPanel';
import StructuralLiquidityPanel from './components/StructuralLiquidityPanel';
import PortfolioBondScreener from './components/PortfolioBondScreener';
import PortfolioConstruction from './components/PortfolioConstruction';
import PortfolioScenarios from './components/PortfolioScenarios';
import { refreshData, getBonds, getFredData } from './utils/api';

const PLACEHOLDER_TABS = ['NEWS', 'BRIEFING'];
const TAB_ORDER = ['DASHBOARD', 'REGIME MAP', 'CROSS-ASSET', 'EQUITIES', 'LIQUIDITY', 'PORTFOLIO', 'NEWS', 'BRIEFING'];
const AUTO_REFRESH_INTERVALS = [0, 900000, 1800000, 3600000]; // manual, 15m, 30m, 1h
const INTERVAL_LABELS = ['MANUAL', '15 MIN', '30 MIN', '1 HOUR'];

export default function App() {
  const [activeTab, setActiveTab] = useState('CROSS-ASSET');
  const [isLoading, setIsLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [fredKey, setFredKey] = useState('');

  // Portfolio state — lifted to App level so it persists across tab switches
  const [portfolio, setPortfolio] = useState([]);
  const [clientSettings, setClientSettings] = useState({
    clientName: '', investmentAmount: 200000, targetReturn: 5.5,
    riskTolerance: 'Moderate',
    fees: { management: 0.5, performance: 0, formation: 0.1, custody: 0.2, trading: 0.2 },
  });
  const [showSetup, setShowSetup] = useState(false);
  const [refreshError, setRefreshError] = useState(null);
  const [refreshResult, setRefreshResult] = useState(null);
  const [autoRefreshIdx, setAutoRefreshIdx] = useState(0);
  const [showRegimes, setShowRegimes] = useState(false);
  const autoRefreshTimer = useRef(null);

  const handleRefresh = useCallback(async () => {
    setIsLoading(true);
    setRefreshError(null);
    try {
      const result = await refreshData();
      setLastRefresh(result.last_refresh);
      setRefreshResult(result);
    } catch (e) {
      setRefreshError(e.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Auto-refresh
  useEffect(() => {
    if (autoRefreshTimer.current) clearInterval(autoRefreshTimer.current);
    const interval = AUTO_REFRESH_INTERVALS[autoRefreshIdx];
    if (interval > 0) {
      autoRefreshTimer.current = setInterval(() => {
        handleRefresh();
      }, interval);
    }
    return () => { if (autoRefreshTimer.current) clearInterval(autoRefreshTimer.current); };
  }, [autoRefreshIdx, handleRefresh]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      // Don't capture when typing in inputs
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      switch (e.key.toLowerCase()) {
        case 'r':
          if (!e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            e.preventDefault();
            handleRefresh();
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
        onRefresh={handleRefresh}
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

      {/* Refresh status toast */}
      {refreshError && (
        <div style={{
          position: 'fixed', bottom: 20, right: 20, zIndex: 1000,
          background: '#1a0000', border: `1px solid ${COLORS.red}44`,
          padding: '10px 16px', fontFamily: FONT, fontSize: 11, color: COLORS.red,
          maxWidth: 400,
        }}>
          Refresh error: {refreshError}
          <button onClick={() => setRefreshError(null)} style={{
            background: 'none', border: 'none', color: COLORS.textMuted, marginLeft: 12, cursor: 'pointer',
          }}>×</button>
        </div>
      )}
      {refreshResult && !refreshError && lastRefresh && (
        <div style={{
          position: 'fixed', bottom: 20, right: 20, zIndex: 1000,
          background: '#001a00', border: `1px solid ${COLORS.green}44`,
          padding: '10px 16px', fontFamily: FONT, fontSize: 11, color: COLORS.green,
        }}>
          Data loaded: {refreshResult.fred_series_count} FRED, {refreshResult.yahoo_series_count} Yahoo
          {refreshResult.gli?.fed === 'ok' && ', GLI Fed'}
          {refreshResult.gli?.cb === 'ok' && ', GLI CB'}
          {refreshResult.gli?.bis === 'ok' && ', GLI BIS'}
          <button onClick={() => setRefreshResult(null)} style={{
            background: 'none', border: 'none', color: COLORS.textMuted, marginLeft: 12, cursor: 'pointer',
          }}>×</button>
        </div>
      )}

      {/* Main content */}
      <div style={{ padding: '0 16px 16px 16px' }}>
        {activeTab === 'DASHBOARD' && <DashboardTab />}
        {activeTab === 'REGIME MAP' && <RegimeMapTab />}
        {activeTab === 'CROSS-ASSET' && <CrossAssetRegimes />}
        {activeTab === 'EQUITIES' && <EquitiesPanel />}
        {activeTab === 'LIQUIDITY' && <LiquidityTab />}
        {activeTab === 'PORTFOLIO' && <PortfolioTab portfolio={portfolio} setPortfolio={setPortfolio}
          clientSettings={clientSettings} setClientSettings={setClientSettings} />}
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

const LIQUIDITY_TABS = [
  'US FUNDING', 'LIQUIDITY DRIVERS', 'GLOBAL NET LIQUIDITY', 'DOLLAR STRESS',
  'COMPOSITE', 'DOLLAR FUNDING', 'CREDIT & SPREADS', 'STRUCTURAL',
  'FOREIGN HOLDERS',
];

const LIQUIDITY_INFO = {
  'US FUNDING': 'Fed net liquidity = WALCL - Currency in Circ - RRP - TGA. This is the highest-frequency liquidity signal (weekly). Howell\'s research shows it correlates strongly with equity prices with a ~6 week lead.',
  'LIQUIDITY DRIVERS': 'Z-score momentum (0-100) of the four major central bank balance sheets. Measures whether CB liquidity is expanding or contracting relative to trend. Below 30 = contractionary (QT), above 70 = expansionary (QE). The 65-month sine wave is Howell\'s empirical cycle fitted since 1965.',
  'GLOBAL NET LIQUIDITY': 'Combined G4 central bank balance sheets in USD (Fed + ECB + BoJ + PBoC). This is Layer B of the Howell framework \u2014 the \'tides\' that drive credit creation. These are additive because they are four distinct institutions.',
  'DOLLAR STRESS': 'Fed balance sheet vs non-USD central banks. When the Fed\'s share of G4 liquidity rises, dollar liquidity is relatively abundant. When non-USD CBs expand faster, it signals potential dollar shortage stress.',
  'COMPOSITE': 'Production liquidity composite signal (4F/3FB/2F models). Synthesizes quantity, credit, M2, and dollar stress components into a single tightening/loosening reading with walk-forward validated weights.',
  'DOLLAR FUNDING': 'Cross-currency basis swaps for 5 major currency pairs. Measures offshore dollar funding stress — negative basis = premium for USD. Uses GDP-weighted Dollar Stress Index.',
  'CREDIT & SPREADS': 'HY OAS credit spreads from ICE BofA. Monitors credit risk repricing — widening spreads signal risk-off, compressing spreads signal risk appetite.',
  'STRUCTURAL': 'BIS total credit to non-financial sector across ~45 countries. Slow-moving structural credit cycle data (quarterly). The debt/liquidity ratio flags refinancing stress.',
  'FOREIGN HOLDERS': 'Major foreign holders of US Treasury securities. Tracks official sector demand for safe assets and dollar reserve accumulation/depletion.',
};

function LiquidityTab() {
  const [section, setSection] = useState('signal');
  const [monitorTab, setMonitorTab] = useState('US FUNDING');
  const [signalTab, setSignalTab] = useState('COMPOSITE');
  const [showInfo, setShowInfo] = useState(null);

  const MONITOR_TABS = {
    'US FUNDING': { component: <USFundingPanel />, label: 'US Funding' },
    'LIQUIDITY DRIVERS': { component: <LiquidityDriversPanel />, label: 'Liquidity Drivers' },
    'GLOBAL NET LIQUIDITY': { component: <GlobalNetLiquidityPanel />, label: 'Global Net Liquidity' },
    'DOLLAR STRESS': { component: <DollarStressPanel />, label: 'Dollar Stress' },
    'FOREIGN HOLDERS': { component: <TICHoldingsPanel />, label: 'Foreign Holders' },
  };

  const SIGNAL_TABS = {
    'COMPOSITE': { component: <LiquidityCompositePanel />, label: 'Composite (Production 5F)' },
    'DOLLAR FUNDING': { component: <DollarFundingPanel />, label: 'Dollar Funding' },
    'CREDIT & SPREADS': { component: <CreditSpreadsPanel />, label: 'Credit & Spreads' },
    'STRUCTURAL': { component: <StructuralLiquidityPanel />, label: 'Structural' },
  };

  const selectStyle = {
    background: '#0a0a0a', color: COLORS.amber, border: `1px solid ${COLORS.amber}44`,
    fontFamily: FONT, fontSize: 12, padding: '5px 12px', cursor: 'pointer',
    borderRadius: 2, minWidth: 180,
  };

  return (
    <div style={{ padding: '8px 0' }}>
      {/* Section tabs */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, borderBottom: `1px solid ${COLORS.cardBorder}`, marginBottom: 10 }}>
        <button onClick={() => setSection('signal')} style={{
          background: 'none', border: 'none', padding: '8px 16px', cursor: 'pointer',
          borderBottom: section === 'signal' ? `2px solid ${COLORS.amber}` : '2px solid transparent',
          color: section === 'signal' ? COLORS.amber : COLORS.textMuted,
          fontFamily: FONT, fontSize: 12, letterSpacing: 1, fontWeight: 'bold',
        }}>GLI SIGNAL & ANALYTICS</button>
        <button onClick={() => setSection('monitor')} style={{
          background: 'none', border: 'none', padding: '8px 16px', cursor: 'pointer',
          borderBottom: section === 'monitor' ? `2px solid ${COLORS.amber}` : '2px solid transparent',
          color: section === 'monitor' ? COLORS.amber : COLORS.textMuted,
          fontFamily: FONT, fontSize: 12, letterSpacing: 1, fontWeight: 'bold',
        }}>GLOBAL LIQUIDITY MONITOR</button>
        <button onClick={() => setSection('test')} style={{
          background: 'none', border: 'none', padding: '8px 16px', cursor: 'pointer',
          borderBottom: section === 'test' ? `2px solid ${COLORS.red}` : '2px solid transparent',
          color: section === 'test' ? COLORS.red : COLORS.textDim,
          fontFamily: FONT, fontSize: 11, letterSpacing: 1,
        }}>TEST</button>
      </div>

      {/* GLI Signal section */}
      {section === 'signal' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <select value={signalTab} onChange={e => setSignalTab(e.target.value)} style={selectStyle}>
              {Object.entries(SIGNAL_TABS).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
            <button onClick={() => setShowInfo(signalTab)}
              style={{ padding: '3px 8px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              &#8505; Methodology
            </button>
          </div>
          {SIGNAL_TABS[signalTab]?.component}
        </div>
      )}

      {/* Global Liquidity Monitor section */}
      {section === 'monitor' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <select value={monitorTab} onChange={e => setMonitorTab(e.target.value)}
              style={{...selectStyle, color: COLORS.textMuted, borderColor: COLORS.cardBorder}}>
              {Object.entries(MONITOR_TABS).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
            <button onClick={() => setShowInfo(monitorTab)}
              style={{ padding: '3px 8px', background: 'none', color: COLORS.cyan,
                border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer' }}>
              &#8505; Methodology
            </button>
          </div>
          {MONITOR_TABS[monitorTab]?.component}
        </div>
      )}

      {/* TEST section */}
      {section === 'test' && (
        <div>
          <div style={{ padding: '8px 12px', marginBottom: 12, background: '#1a0000',
            border: `1px solid ${COLORS.red}44`, fontSize: 11, color: COLORS.red }}>
            ⚠ EXPERIMENTAL — NOT PRODUCTION. Results in this section are under development and have not been validated.
          </div>
          <div style={{ padding: 20, color: COLORS.textDim, fontSize: 11, textAlign: 'center' }}>
            Howell reverse-engineering panels will appear here once Phase 1-2 data is available.
            <br />Run the Howell analysis endpoint to populate.
          </div>
        </div>
      )}

      {/* Methodology modal */}
      {showInfo && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
          onClick={() => setShowInfo(null)}>
          <div style={{ background: '#111', border: `1px solid ${COLORS.cyan}44`, padding: 24, width: 560,
            fontFamily: FONT }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <h3 style={{ color: COLORS.amber, fontSize: 14, margin: 0, letterSpacing: 1 }}>{showInfo}</h3>
              <button onClick={() => setShowInfo(null)} style={{
                background: 'none', border: 'none', color: COLORS.textMuted, fontSize: 18, cursor: 'pointer' }}>×</button>
            </div>
            <div style={{ fontSize: 12, color: COLORS.textSecondary, lineHeight: 1.8 }}>
              {LIQUIDITY_INFO[showInfo]}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const PORTFOLIO_TABS = ['SCREENER', 'PORTFOLIO', 'SCENARIOS', 'SUMMARY'];

function PortfolioTab({ portfolio, setPortfolio, clientSettings, setClientSettings }) {
  const [subTab, setSubTab] = useState('SCREENER');
  const [bondUniverse, setBondUniverse] = useState([]);
  const [treasuryCurve, setTreasuryCurve] = useState(null);

  // Fetch bond universe and FRED Treasury curve when scenarios tab is active
  useEffect(() => {
    if (subTab === 'SCENARIOS') {
      getBonds({}).then(r => { if (r?.bonds) setBondUniverse(r.bonds); }).catch(() => {});
      getFredData('DGS1,DGS2,DGS5,DGS10,DGS30').then(data => {
        if (Array.isArray(data) && data.length > 0) {
          // Get latest non-null row
          for (let i = data.length - 1; i >= 0; i--) {
            const row = data[i];
            if (row.DGS10 != null) { setTreasuryCurve(row); break; }
          }
        }
      }).catch(() => {});
    }
  }, [subTab]);

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
      {subTab === 'PORTFOLIO' && (
        <PortfolioConstruction portfolio={portfolio} setPortfolio={setPortfolio}
          clientSettings={clientSettings} setClientSettings={setClientSettings}
          onAddEquity={addToPortfolio} />
      )}
      {subTab === 'SCENARIOS' && (
        <PortfolioScenarios portfolio={portfolio} clientSettings={clientSettings}
          bondUniverse={bondUniverse} treasuryCurve={treasuryCurve} />
      )}
      {subTab === 'SUMMARY' && (
        <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontSize: 13 }}>
          <div style={{ fontSize: 18, color: COLORS.amber, letterSpacing: 2, marginBottom: 12 }}>SUMMARY</div>
          <div>Coming soon — one-page view for PM discussion</div>
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
