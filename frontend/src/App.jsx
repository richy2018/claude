import React, { useState, useCallback } from 'react';
import { COLORS, FONT } from './utils/theme';
import HeaderBar from './components/HeaderBar';
import NavBar from './components/NavBar';
import CrossAssetRegimes from './components/CrossAssetRegimes';
import STIRPanel from './components/STIRPanel';
import FairValuePanel from './components/FairValuePanel';
import { refreshData } from './utils/api';

const PLACEHOLDER_TABS = ['REGIME MAP', 'NEWS', 'BRIEFING'];

export default function App() {
  const [activeTab, setActiveTab] = useState('CROSS-ASSET');
  const [isLoading, setIsLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [fredKey, setFredKey] = useState('');
  const [showSetup, setShowSetup] = useState(false);
  const [refreshError, setRefreshError] = useState(null);
  const [refreshResult, setRefreshResult] = useState(null);

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

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: COLORS.bg,
      fontFamily: FONT,
      color: COLORS.white,
    }}>
      <HeaderBar
        onRefresh={() => {
          if (!fredKey) {
            setShowSetup(true);
          } else {
            handleRefresh();
          }
        }}
        isLoading={isLoading}
        lastRefresh={lastRefresh}
      />
      <NavBar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Setup modal for API key */}
      {showSetup && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.85)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
        }}>
          <div style={{
            backgroundColor: '#111',
            border: `1px solid ${COLORS.amber}44`,
            padding: 32,
            width: 480,
            fontFamily: FONT,
          }}>
            <h3 style={{ color: COLORS.amber, fontSize: 14, marginBottom: 16, letterSpacing: 1 }}>
              DATA SOURCE CONFIGURATION
            </h3>
            <label style={{ display: 'block', color: COLORS.textMuted, fontSize: 11, marginBottom: 6 }}>
              FRED API KEY
            </label>
            <input
              type="text"
              value={fredKey}
              onChange={(e) => setFredKey(e.target.value)}
              placeholder="Enter your FRED API key..."
              style={{
                width: '100%',
                padding: '8px 12px',
                backgroundColor: '#0a0a0a',
                border: `1px solid ${COLORS.cardBorder}`,
                color: COLORS.white,
                fontFamily: FONT,
                fontSize: 12,
                outline: 'none',
                marginBottom: 16,
              }}
            />
            <div style={{ color: COLORS.textMuted, fontSize: 10, marginBottom: 16 }}>
              Get a free API key from{' '}
              <span style={{ color: COLORS.cyan }}>https://fred.stlouisfed.org/docs/api/api_key.html</span>
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
                  border: 'none',
                  fontFamily: FONT,
                  fontSize: 12,
                  letterSpacing: 1,
                  cursor: fredKey ? 'pointer' : 'not-allowed',
                }}
              >
                {isLoading ? 'LOADING...' : 'FETCH DATA'}
              </button>
              <button
                onClick={() => setShowSetup(false)}
                style={{
                  padding: '8px 20px',
                  backgroundColor: 'transparent',
                  color: COLORS.textMuted,
                  border: `1px solid ${COLORS.cardBorder}`,
                  fontFamily: FONT,
                  fontSize: 12,
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
          </div>
        </div>
      )}

      {/* Main content area */}
      <div style={{ padding: '0 16px 16px 16px' }}>
        {activeTab === 'CROSS-ASSET' && <CrossAssetRegimes />}

        {activeTab === 'DASHBOARD' && (
          <DashboardTab onSetup={() => setShowSetup(true)} hasData={!!lastRefresh} />
        )}

        {activeTab === 'EQUITIES' && (
          <PlaceholderPanel title="EQUITIES" subtitle="Sector-level factor analysis" />
        )}

        {PLACEHOLDER_TABS.includes(activeTab) && (
          <PlaceholderPanel title={activeTab} subtitle="Coming soon" />
        )}
      </div>
    </div>
  );
}

function DashboardTab({ onSetup, hasData }) {
  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 12,
      }}>
        {/* Left panel: STIR */}
        <div style={{
          backgroundColor: COLORS.card,
          border: `1px solid ${COLORS.cardBorder}`,
          padding: 16,
          minHeight: 400,
        }}>
          <STIRPanel />
        </div>

        {/* Right panel: Fair Value Model */}
        <div style={{
          backgroundColor: COLORS.card,
          border: `1px solid ${COLORS.cardBorder}`,
          padding: 16,
          minHeight: 400,
          overflowY: 'auto',
        }}>
          <FairValuePanel />
        </div>
      </div>
    </div>
  );
}

function PlaceholderPanel({ title, subtitle }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: 400,
      color: COLORS.textMuted,
    }}>
      <div style={{ fontSize: 24, color: COLORS.amber, letterSpacing: 3, marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 12 }}>{subtitle}</div>
    </div>
  );
}
