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
import CreditCollateralPanel from './components/CreditCollateralPanel';
import DollarStressPanel from './components/DollarStressPanel';
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

const LIQUIDITY_TABS = ['US FUNDING', 'LIQUIDITY DRIVERS', 'GLOBAL NET LIQUIDITY', 'DOLLAR STRESS', 'CREDIT & COLLATERAL', 'FOREIGN HOLDERS'];

const LIQUIDITY_INFO = {
  'US FUNDING': 'Fed net liquidity = WALCL - Currency in Circ - RRP - TGA. This is the highest-frequency liquidity signal (weekly). Howell\'s research shows it correlates strongly with equity prices with a ~6 week lead.',
  'LIQUIDITY DRIVERS': 'Z-score momentum (0-100) of the four major central bank balance sheets. Measures whether CB liquidity is expanding or contracting relative to trend. Below 30 = contractionary (QT), above 70 = expansionary (QE). The 65-month sine wave is Howell\'s empirical cycle fitted since 1965.',
  'GLOBAL NET LIQUIDITY': 'Combined G4 central bank balance sheets in USD (Fed + ECB + BoJ + PBoC). This is Layer B of the Howell framework \u2014 the \'tides\' that drive credit creation. These are additive because they are four distinct institutions.',
  'DOLLAR STRESS': 'Fed balance sheet vs non-USD central banks. When the Fed\'s share of G4 liquidity rises, dollar liquidity is relatively abundant. When non-USD CBs expand faster, it signals potential dollar shortage stress.',
  'CREDIT & COLLATERAL': 'BIS total credit to the non-financial sector across ~45 countries. This is Layer A \u2014 the \'ocean\' of global liquidity (~$175T). The debt/liquidity ratio flags refinancing stress when total debt outpaces private credit capacity.',
  'FOREIGN HOLDERS': 'Major foreign holders of US Treasury securities. Tracks official sector demand for safe assets and dollar reserve accumulation/depletion.',
};

function LiquidityTab() {
  const [subTab, setSubTab] = useState('US FUNDING');
  const [infoTab, setInfoTab] = useState(null);
  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{
        display: 'flex', gap: 0,
        borderBottom: `1px solid ${COLORS.cardBorder}`, marginBottom: 8,
      }}>
        {LIQUIDITY_TABS.map(tab => (
          <div key={tab} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <button onClick={() => setSubTab(tab)} style={{
              background: 'none', border: 'none',
              borderBottom: subTab === tab ? `2px solid ${COLORS.amber}` : '2px solid transparent',
              color: subTab === tab ? COLORS.amber : COLORS.textMuted,
              fontFamily: FONT, fontSize: 13, letterSpacing: 1,
              padding: '8px 12px 8px 16px', cursor: 'pointer',
            }}>{tab}</button>
            <span
              onClick={(e) => { e.stopPropagation(); setInfoTab(infoTab === tab ? null : tab); }}
              style={{
                cursor: 'pointer', fontSize: 11, color: COLORS.textDim,
                marginRight: 4, userSelect: 'none',
              }}
            >&#9432;</span>
            {infoTab === tab && (
              <div style={{
                position: 'absolute', top: '100%', left: 0, zIndex: 100,
                background: '#111', border: `1px solid ${COLORS.amber}44`,
                padding: '10px 14px', width: 320, fontFamily: FONT,
                fontSize: 11, color: COLORS.textMuted, lineHeight: 1.6,
                marginTop: 4, borderRadius: 2,
              }}>
                {LIQUIDITY_INFO[tab]}
                <div style={{ textAlign: 'right', marginTop: 6 }}>
                  <span onClick={() => setInfoTab(null)} style={{ color: COLORS.textDim, cursor: 'pointer', fontSize: 10 }}>close</span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      {subTab === 'US FUNDING' && <USFundingPanel />}
      {subTab === 'LIQUIDITY DRIVERS' && <LiquidityDriversPanel />}
      {subTab === 'GLOBAL NET LIQUIDITY' && <GlobalNetLiquidityPanel />}
      {subTab === 'DOLLAR STRESS' && <DollarStressPanel />}
      {subTab === 'CREDIT & COLLATERAL' && <CreditCollateralPanel />}
      {subTab === 'FOREIGN HOLDERS' && <TICHoldingsPanel />}
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
