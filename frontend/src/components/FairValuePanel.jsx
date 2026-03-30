import React, { useState, useEffect } from 'react';
import { COLORS, FONT } from '../utils/theme';
import { getFairValue } from '../utils/api';
import InflationModelView from './InflationModelView';
import GrowthView from './GrowthView';

const MODEL_TABS = ['CPI MODEL', 'PCE MODEL', 'PPI MODEL', 'SWAP DYNAMICS', 'GROWTH', 'TRIANGULATION'];

const MODEL_MAP = {
  'CPI MODEL': 'cpi',
  'PCE MODEL': 'pce',
  'PPI MODEL': 'ppi',
};

export default function FairValuePanel() {
  const [activeModel, setActiveModel] = useState('CPI MODEL');
  const [measure, setMeasure] = useState('headline');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const modelKey = MODEL_MAP[activeModel];
    if (!modelKey) return; // Growth, Swap Dynamics, Triangulation handled differently

    let cancelled = false;
    setLoading(true);
    setError(null);

    getFairValue(modelKey, measure)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [activeModel, measure]);

  const isInflationModel = activeModel in MODEL_MAP;
  const isGrowth = activeModel === 'GROWTH';
  const isPlaceholder = activeModel === 'SWAP DYNAMICS' || activeModel === 'TRIANGULATION';

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 10,
      }}>
        <h3 style={{ color: COLORS.amber, fontSize: 14, letterSpacing: 1, margin: 0 }}>
          FAIR VALUE MODEL
        </h3>
        <div style={{ display: 'flex', gap: 6 }}>
          {['HEADLINE', 'CORE'].map((m) => (
            <button
              key={m}
              onClick={() => setMeasure(m.toLowerCase())}
              style={{
                padding: '3px 10px',
                backgroundColor: measure === m.toLowerCase() ? COLORS.amber : 'transparent',
                color: measure === m.toLowerCase() ? '#0a0a0a' : COLORS.textMuted,
                border: `1px solid ${measure === m.toLowerCase() ? COLORS.amber : COLORS.cardBorder}`,
                fontFamily: FONT,
                fontSize: 11,
                cursor: 'pointer',
              }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* Model tabs */}
      <div style={{
        display: 'flex',
        gap: 3,
        marginBottom: 12,
        flexWrap: 'wrap',
      }}>
        {MODEL_TABS.map((tab) => {
          const isActive = activeModel === tab;
          const isDisabled = tab === 'SWAP DYNAMICS' || tab === 'TRIANGULATION';
          return (
            <button
              key={tab}
              onClick={() => setActiveModel(tab)}
              style={{
                padding: '4px 10px',
                backgroundColor: isActive ? COLORS.amber : 'transparent',
                color: isActive ? '#0a0a0a' : isDisabled ? '#333' : COLORS.textMuted,
                border: `1px solid ${isActive ? COLORS.amber : COLORS.cardBorder}`,
                fontFamily: FONT,
                fontSize: 10,
                cursor: isDisabled ? 'default' : 'pointer',
                opacity: isDisabled ? 0.5 : 1,
              }}
            >
              {tab}
            </button>
          );
        })}
      </div>

      {/* Content */}
      {loading && (
        <div style={{ padding: 20, color: COLORS.amber, fontSize: 12 }}>
          Loading {activeModel.toLowerCase()} data...
        </div>
      )}

      {error && (
        <div style={{ padding: 20, color: COLORS.red, fontSize: 12 }}>
          Error: {error}
          <div style={{ color: COLORS.textMuted, fontSize: 10, marginTop: 8 }}>
            Make sure data has been loaded via REFRESH first.
          </div>
        </div>
      )}

      {!loading && !error && isInflationModel && data && (
        <InflationModelView data={data} />
      )}

      {isGrowth && <GrowthView />}

      {isPlaceholder && (
        <div style={{
          padding: 40,
          textAlign: 'center',
          color: COLORS.textMuted,
          fontSize: 12,
        }}>
          <div style={{ fontSize: 16, color: COLORS.amber, letterSpacing: 2, marginBottom: 12 }}>
            {activeModel}
          </div>
          <div>
            {activeModel === 'SWAP DYNAMICS'
              ? 'Coming soon — Inflation swap rates, breakeven decomposition, real vs nominal rate dynamics'
              : 'Coming soon — CPI vs PCE vs PPI signal comparison, convergence/divergence analysis'}
          </div>
        </div>
      )}
    </div>
  );
}
