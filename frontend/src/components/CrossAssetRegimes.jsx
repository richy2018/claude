import React, { useState, useEffect, useCallback } from 'react';
import { COLORS, FONT } from '../utils/theme';
import ControlsRow, { rangeToDays } from './ControlsRow';
import CurrentRegimeBanner from './CurrentRegimeBanner';
import RegimeTimeline from './RegimeTimeline';
import RegimeFrequency from './RegimeFrequency';
import MarketLinkage from './MarketLinkage';
import TransitionsView from './TransitionsView';
import SynthesisView from './SynthesisView';
import { getRegimes } from '../utils/api';

const SUB_TABS = ['REGIMES', 'ATTRIBUTION', 'TRANSITIONS', 'SYNTHESIS'];

export default function CrossAssetRegimes() {
  const [subTab, setSubTab] = useState('REGIMES');
  const [method, setMethod] = useState('vol-scaled');
  const [lookback, setLookback] = useState(21);
  const [volWindow, setVolWindow] = useState(21);
  const [range, setRange] = useState('2Y');
  const [focus, setFocus] = useState('ALL');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchRegimes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const days = rangeToDays(range);
      const result = await getRegimes({
        lookback,
        volWindow,
        volScaled: method === 'vol-scaled',
        rangeDays: days,
      });
      setData(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [method, lookback, volWindow, range]);

  useEffect(() => {
    fetchRegimes();
  }, [fetchRegimes]);

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white }}>
      {/* Page header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '12px 0' }}>
        <h2 style={{ margin: 0, fontSize: 18, color: COLORS.amber, letterSpacing: 2, fontWeight: 'bold' }}>
          CROSS-ASSET REGIMES
        </h2>
        <span style={{ fontSize: 12, color: COLORS.textMuted }}>SPX + UST 10Y + DXY</span>
        {data && (
          <div style={{
            marginLeft: 'auto',
            display: 'flex',
            gap: 16,
            fontSize: 12,
            alignItems: 'center',
          }}>
            <span style={{
              padding: '4px 10px',
              border: `1px solid ${COLORS.amber}44`,
              color: COLORS.amber,
              fontSize: 11,
            }}>
              MARKET LINKAGE {data.linkage_label} ({Math.round(data.current_linkage)}%)
            </span>
            <span style={{ color: COLORS.white }}>
              SPX <strong>{data.spx_last?.toLocaleString(undefined, { maximumFractionDigits: 2 })}</strong>
            </span>
            <span style={{ color: COLORS.white }}>
              10Y <strong>{data.rates_last?.toFixed(3)}%</strong>
            </span>
            <span style={{ color: COLORS.white }}>
              DXY <strong>{data.dxy_last?.toFixed(2)}</strong>
            </span>
          </div>
        )}
      </div>

      {/* Sub-tabs */}
      <div style={{
        display: 'flex',
        gap: 0,
        borderBottom: `1px solid ${COLORS.cardBorder}`,
        marginBottom: 8,
      }}>
        {SUB_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setSubTab(tab)}
            style={{
              background: 'none',
              border: 'none',
              borderBottom: subTab === tab ? `2px solid ${COLORS.amber}` : '2px solid transparent',
              color: subTab === tab ? COLORS.amber : COLORS.textMuted,
              fontFamily: FONT,
              fontSize: 13,
              letterSpacing: 1,
              padding: '8px 20px',
              cursor: 'pointer',
              opacity: tab === 'ATTRIBUTION' ? 0.4 : 1,
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Controls */}
      <ControlsRow
        method={method}
        lookback={lookback}
        volWindow={volWindow}
        range={range}
        onMethodChange={setMethod}
        onLookbackChange={setLookback}
        onVolWindowChange={setVolWindow}
        onRangeChange={setRange}
      />

      {/* Loading / Error */}
      {loading && (
        <div style={{ padding: 20, color: COLORS.amber, fontSize: 13 }}>
          Loading regime data...
        </div>
      )}
      {error && (
        <div style={{ padding: 20, color: COLORS.red, fontSize: 13 }}>
          Error: {error}
        </div>
      )}

      {/* Main content — REGIMES tab */}
      {!loading && data && subTab === 'REGIMES' && (
        <>
          {/* Current regime banner */}
          <CurrentRegimeBanner
            regime={data.current_regime}
            description={data.current_description}
            color={data.current_color}
            spxMetric={data.current_spx_metric}
            ratesMetric={data.current_rates_metric}
            dxyMetric={data.current_dxy_metric}
            linkage={data.current_linkage}
            linkageLabel={data.linkage_label}
          />

          {/* Two-column layout */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8 }}>
            {/* Left: Timeline */}
            <div style={{
              backgroundColor: COLORS.card,
              border: `1px solid ${COLORS.cardBorder}`,
              padding: 12,
            }}>
              <RegimeTimeline
                timeline={data.timeline}
                title={`${data.total_days} days`}
              />
            </div>

            {/* Right: Frequency */}
            <div style={{
              backgroundColor: COLORS.card,
              border: `1px solid ${COLORS.cardBorder}`,
              padding: 12,
            }}>
              <RegimeFrequency stats={data.stats} />
            </div>
          </div>

          {/* Bottom: Market Linkage */}
          <div style={{
            backgroundColor: COLORS.card,
            border: `1px solid ${COLORS.cardBorder}`,
            padding: 12,
            marginTop: 12,
          }}>
            <MarketLinkage
              linkageTimeline={data.linkage_timeline}
              currentLinkage={data.current_linkage}
              linkageLabel={data.linkage_label}
            />
          </div>
        </>
      )}

      {/* TRANSITIONS sub-tab */}
      {!loading && subTab === 'TRANSITIONS' && data && (
        <>
          {/* Focus filter */}
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', margin: '8px 0' }}>
            <span style={{ color: COLORS.textMuted, fontSize: 11, marginRight: 8 }}>FOCUS:</span>
            {['ALL', 'SPX', '10Y', 'DXY'].map((f) => (
              <button
                key={f}
                onClick={() => setFocus(f)}
                style={{
                  padding: '3px 10px',
                  backgroundColor: focus === f ? COLORS.amber : '#1a1a1a',
                  color: focus === f ? '#0a0a0a' : '#888',
                  border: `1px solid ${focus === f ? COLORS.amber : '#333'}`,
                  fontFamily: FONT,
                  fontSize: 11,
                  cursor: 'pointer',
                }}
              >
                {f}
              </button>
            ))}
          </div>
          <CurrentRegimeBanner
            regime={data.current_regime}
            description={data.current_description}
            color={data.current_color}
            spxMetric={data.current_spx_metric}
            ratesMetric={data.current_rates_metric}
            dxyMetric={data.current_dxy_metric}
            linkage={data.current_linkage}
            linkageLabel={data.linkage_label}
          />
          <TransitionsView data={data} focus={focus} />
        </>
      )}

      {/* ATTRIBUTION sub-tab (placeholder) */}
      {!loading && subTab === 'ATTRIBUTION' && (
        <div style={{
          padding: 40,
          textAlign: 'center',
          color: COLORS.textMuted,
          fontSize: 13,
        }}>
          <div style={{ fontSize: 18, color: COLORS.amber, letterSpacing: 2, marginBottom: 12 }}>
            ATTRIBUTION
          </div>
          <div style={{ maxWidth: 500, margin: '0 auto', lineHeight: 1.6 }}>
            Coming soon — This will contain:
            <ul style={{ textAlign: 'left', marginTop: 12, color: COLORS.textSecondary }}>
              <li>Which asset is driving the current regime most</li>
              <li>Decomposition of regime changes into SPX/10Y/DXY contributions</li>
              <li>Rolling attribution over time</li>
            </ul>
          </div>
        </div>
      )}

      {/* SYNTHESIS sub-tab */}
      {!loading && subTab === 'SYNTHESIS' && data && (
        <SynthesisView
          regimeData={data}
          method={method}
          lookback={lookback}
          volWindow={volWindow}
        />
      )}
    </div>
  );
}
