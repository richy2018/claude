import React from 'react';
import { COLORS, FONT } from '../utils/theme';

export default function PortfolioSettings({ clientSettings, setClientSettings, portfolio, setPortfolio }) {
  const update = (key, val) => setClientSettings(prev => ({ ...prev, [key]: val }));
  const updateFee = (key, val) => setClientSettings(prev => ({
    ...prev, fees: { ...prev.fees, [key]: parseFloat(val) || 0 }
  }));

  const handleSave = () => {
    const data = { portfolio, clientSettings, savedAt: new Date().toISOString() };
    localStorage.setItem('portfolio_builder_save', JSON.stringify(data));
    alert('Portfolio saved to browser storage');
  };

  const handleLoad = () => {
    const raw = localStorage.getItem('portfolio_builder_save');
    if (!raw) { alert('No saved portfolio found'); return; }
    try {
      const data = JSON.parse(raw);
      if (data.portfolio) setPortfolio(data.portfolio);
      if (data.clientSettings) setClientSettings(data.clientSettings);
      alert(`Loaded portfolio from ${data.savedAt || 'unknown date'}`);
    } catch { alert('Failed to load saved portfolio'); }
  };

  const inputStyle = {
    padding: '6px 10px', background: COLORS.bg, border: `1px solid ${COLORS.cardBorder}`,
    color: COLORS.white, fontFamily: FONT, fontSize: 12, outline: 'none', width: 200,
  };

  const labelStyle = { fontSize: 10, color: COLORS.textMuted, marginBottom: 4, display: 'block', letterSpacing: '0.05em' };

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white, maxWidth: 600 }}>
      <h2 style={{ fontSize: 18, color: COLORS.amber, letterSpacing: 2, marginBottom: 16 }}>CLIENT CONFIGURATION</h2>

      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 16, marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 12 }}>CLIENT DETAILS</div>
        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>CLIENT NAME</label>
          <input value={clientSettings.clientName || ''} onChange={e => update('clientName', e.target.value)}
            placeholder="Client name..." style={inputStyle} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>INVESTMENT AMOUNT (EUR)</label>
          <input type="number" value={clientSettings.investmentAmount || 200000}
            onChange={e => update('investmentAmount', parseFloat(e.target.value) || 0)} style={inputStyle} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>TARGET NET RETURN (%)</label>
          <input type="number" step="0.1" value={clientSettings.targetReturn || 5.5}
            onChange={e => update('targetReturn', parseFloat(e.target.value) || 0)} style={inputStyle} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>RISK TOLERANCE</label>
          <select value={clientSettings.riskTolerance || 'Moderate'}
            onChange={e => update('riskTolerance', e.target.value)}
            style={{ ...inputStyle, width: 210 }}>
            <option value="Conservative">Conservative (dur&lt;5, HY&lt;30%, eq&lt;10%)</option>
            <option value="Moderate">Moderate (dur&lt;7, HY&lt;50%, eq&lt;20%)</option>
            <option value="Aggressive">Aggressive (dur&lt;10, HY&lt;70%, eq&lt;30%)</option>
          </select>
        </div>
      </div>

      <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 16, marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 12 }}>FEE STRUCTURE</div>
        {[
          { key: 'management', label: 'MANAGEMENT FEE (% P.A.)' },
          { key: 'performance', label: 'PERFORMANCE FEE (%)' },
          { key: 'formation', label: 'FORMATION FEE (% ONE-TIME)' },
          { key: 'custody', label: 'CUSTODY FEE (% P.A.)' },
          { key: 'trading', label: 'TRADING COMMISSION (% PER TRADE)' },
        ].map(f => (
          <div key={f.key} style={{ marginBottom: 10 }}>
            <label style={labelStyle}>{f.label}</label>
            <input type="number" step="0.05"
              value={clientSettings.fees?.[f.key] ?? 0}
              onChange={e => updateFee(f.key, e.target.value)}
              style={{ ...inputStyle, width: 100 }} />
          </div>
        ))}
        <div style={{ fontSize: 10, color: COLORS.textMuted, marginTop: 8, padding: '6px 0', borderTop: `1px solid ${COLORS.cardBorder}` }}>
          Total ongoing: {((clientSettings.fees?.management || 0) + (clientSettings.fees?.custody || 0)).toFixed(2)}% p.a.
          + {(clientSettings.fees?.formation || 0).toFixed(2)}% formation
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button onClick={handleSave} style={{
          padding: '8px 20px', background: COLORS.green, color: COLORS.bg,
          border: 'none', fontFamily: FONT, fontSize: 12, cursor: 'pointer' }}>
          SAVE PORTFOLIO
        </button>
        <button onClick={handleLoad} style={{
          padding: '8px 20px', background: COLORS.cyan, color: COLORS.bg,
          border: 'none', fontFamily: FONT, fontSize: 12, cursor: 'pointer' }}>
          LOAD SAVED
        </button>
        <button onClick={() => { setPortfolio([]); }} style={{
          padding: '8px 20px', background: COLORS.red, color: COLORS.bg,
          border: 'none', fontFamily: FONT, fontSize: 12, cursor: 'pointer' }}>
          RESET PORTFOLIO
        </button>
      </div>
    </div>
  );
}
