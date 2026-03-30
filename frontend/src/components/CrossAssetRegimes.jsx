import React, { useState, useEffect, useCallback } from 'react';
import { COLORS, FONT } from '../utils/theme';
import ControlsRow, { rangeToDays } from './ControlsRow';
import CurrentRegimeBanner from './CurrentRegimeBanner';
import RegimeTimeline from './RegimeTimeline';
import RegimeFrequency from './RegimeFrequency';
import MarketLinkage from './MarketLinkage';
import { getRegimes } from '../utils/api';

const SUB_TABS = ['REGIMES', 'ATTRIBUTION', 'TRANSITIONS', 'SYNTHESIS'];

export default function CrossAssetRegimes() {
  const [subTab, setSubTab] = useState('REGIMES');
  const [method, setMethod] = useState('vol-scaled');
  const [lookback, setLookback] = useState(21);
  const [volWindow, setVolWindow] = useState(21);
  const [range, setRange] = useState('2Y');
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
              cursor: tab === 'REGIMES' || tab === 'TRANSITIONS' ? 'pointer' : 'default',
              opacity: tab === 'ATTRIBUTION' || tab === 'SYNTHESIS' ? 0.4 : 1,
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

      {/* Placeholder for other sub-tabs */}
      {!loading && subTab === 'TRANSITIONS' && data && (
        <div style={{ padding: 20 }}>
          <TransitionsView data={data} />
        </div>
      )}
      {!loading && (subTab === 'ATTRIBUTION' || subTab === 'SYNTHESIS') && (
        <div style={{ padding: 40, textAlign: 'center', color: COLORS.textMuted, fontSize: 13 }}>
          {subTab} — Coming soon
        </div>
      )}
    </div>
  );
}

/**
 * Simple Transitions view showing current state + transition probabilities.
 */
function TransitionsView({ data }) {
  if (!data) return null;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      {/* Current State */}
      <div style={{
        backgroundColor: '#0a0a0a',
        border: `1px solid ${COLORS.cardBorder}`,
        padding: 16,
      }}>
        <h3 style={{ color: COLORS.white, fontSize: 14, margin: '0 0 4px 0' }}>
          CURRENT STATE <span style={{ color: data.current_color, fontSize: 12 }}>{data.current_regime}</span>
        </h3>
        <div style={{
          padding: '8px 12px',
          backgroundColor: `${data.current_color}11`,
          borderLeft: `3px solid ${data.current_color}`,
          color: data.current_color,
          fontSize: 13,
          marginBottom: 16,
        }}>
          {data.current_description}
        </div>
        <div style={{ display: 'flex', gap: 24 }}>
          {[
            { label: 'SPX SIGNAL', value: data.current_spx_metric, color: parseFloat(data.current_spx_metric) >= 0 ? COLORS.green : COLORS.red },
            { label: '10Y SIGNAL', value: data.current_rates_metric, color: COLORS.amber },
            { label: 'DXY SIGNAL', value: data.current_dxy_metric, color: COLORS.cyan },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: COLORS.textMuted, marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 18, color, fontWeight: 'bold' }}>
                {value != null ? (parseFloat(value) >= 0 ? '+' : '') + parseFloat(value).toFixed(2) : '—'}
              </div>
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 16,
          padding: '6px 10px',
          border: `1px solid ${COLORS.amber}33`,
          fontSize: 11,
        }}>
          <div style={{ color: COLORS.textMuted, fontSize: 10 }}>MARKET LINKAGE</div>
          <div style={{ color: COLORS.amber, fontWeight: 'bold' }}>
            {data.linkage_label} ({Math.round(data.current_linkage)}%)
          </div>
          <div style={{ color: COLORS.textMuted, fontSize: 10, marginTop: 4 }}>
            {data.current_linkage > 60
              ? 'All 3 assets are being driven by the same theme. Regime signal is strong.'
              : data.current_linkage > 40
              ? 'Mixed drivers. Regime signal is moderate.'
              : 'Each asset moving on its own drivers. Regime signal is weaker.'}
          </div>
        </div>
      </div>

      {/* What's Next */}
      <div style={{
        backgroundColor: '#0a0a0a',
        border: `1px solid ${COLORS.cardBorder}`,
        padding: 16,
      }}>
        <h3 style={{ color: COLORS.white, fontSize: 14, margin: '0 0 4px 0' }}>
          WHAT'S NEXT <span style={{ color: COLORS.textMuted, fontSize: 11 }}>
            From {data.current_regime} — historical transition probabilities
          </span>
        </h3>
        <div style={{ color: '#ffd600', fontSize: 10, marginBottom: 12, lineHeight: 1.4 }}>
          How to read: PROB = chance of transitioning to that regime next. (stay) = staying in the current regime.
          SPX/10Y/DXY = median daily returns in the destination regime. LINKAGE = how correlated the 3 assets typically are in that regime.
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: FONT }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
              {['TO', 'PROB', 'HIST. OBS'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '4px 8px', color: COLORS.textMuted, fontSize: 10, fontWeight: 'normal' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.from_current?.map((t) => (
              <tr key={t.to} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                <td style={{ padding: '5px 8px' }}>
                  <span style={{
                    display: 'inline-block',
                    width: 8,
                    height: 8,
                    backgroundColor: t.color,
                    marginRight: 6,
                  }} />
                  <span style={{ color: t.color }}>{t.to_label}</span>
                </td>
                <td style={{
                  padding: '5px 8px',
                  color: t.prob > 50 ? COLORS.amber : t.prob > 10 ? COLORS.white : COLORS.textMuted,
                  fontWeight: t.prob > 50 ? 'bold' : 'normal',
                }}>
                  {t.prob}%
                </td>
                <td style={{ padding: '5px 8px', color: COLORS.textMuted }}>
                  {t.hist_obs}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
