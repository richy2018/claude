import React, { useState, useCallback } from 'react';
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getBisGroup } from '../utils/api';

const COUNTRY_COLORS = {
  US: COLORS.amber, XM: COLORS.cyan, JP: COLORS.red,
  GB: COLORS.green, CN: '#ff6600', CH: COLORS.purple,
  DE: COLORS.blue, FR: '#ff80ab', AU: '#22c55e', CA: '#ffcc00',
  '5R': COLORS.white, KR: '#00bcd4', IN: '#e040fb',
};

const SUB_TABS = ['CREDIT & DEBT', 'FX & RATES', 'PROPERTY'];
const GROUP_MAP = { 'CREDIT & DEBT': 'credit', 'FX & RATES': 'fx', 'PROPERTY': 'property' };

function MultiLineChart({ data, title, yLabel, countries, countryNames, height = 280 }) {
  if (!data || Object.keys(data).length === 0) {
    return <div style={{ color: COLORS.textDim, fontSize: 9, padding: 8 }}>No data</div>;
  }

  const merged = [];
  const allDates = new Set();
  Object.entries(data).forEach(([c, pts]) => {
    pts.forEach(p => allDates.add(p.date));
  });
  const sortedDates = [...allDates].sort();

  const lookup = {};
  Object.entries(data).forEach(([c, pts]) => {
    pts.forEach(p => {
      if (!lookup[p.date]) lookup[p.date] = { date: p.date };
      lookup[p.date][c] = p.value;
    });
  });

  const chartData = sortedDates.map(d => lookup[d] || { date: d });
  const cs = Object.keys(data);

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ color: COLORS.textMuted, fontSize: 9, letterSpacing: 1, marginBottom: 4 }}>{title}</div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 15 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.cardBorder} />
          <XAxis dataKey="date" tick={{ fill: COLORS.textDim, fontSize: 8, fontFamily: FONT }}
            tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
          <YAxis tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }}
            label={yLabel ? { value: yLabel, angle: -90, position: 'insideLeft',
              fill: COLORS.textDim, fontSize: 8, fontFamily: FONT } : undefined} />
          <Tooltip contentStyle={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`,
            fontFamily: FONT, fontSize: 10 }} labelFormatter={l => l?.slice(0, 7)} />
          {cs.map(c => (
            <Line key={c} type="monotone" dataKey={c} stroke={COUNTRY_COLORS[c] || COLORS.textMuted}
              strokeWidth={c === 'US' || c === '5R' ? 2 : 1.2} dot={false} connectNulls
              name={countryNames?.[c] || c} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ display: 'flex', gap: 10, justifyContent: 'center', marginTop: 4, flexWrap: 'wrap' }}>
        {cs.map(c => (
          <span key={c} style={{ fontSize: 8, color: COLORS.textMuted }}>
            <span style={{ color: COUNTRY_COLORS[c] || COLORS.textMuted }}>━</span>{' '}
            {countryNames?.[c] || c}
          </span>
        ))}
      </div>
    </div>
  );
}

function MetaBar({ asOf }) {
  if (!asOf || Object.keys(asOf).length === 0) return null;
  const entries = Object.values(asOf).filter(m => m?.latest);
  if (entries.length === 0) return null;
  const freshest = entries.reduce((a, b) => (a.days_behind < b.days_behind ? a : b));
  const stalest = entries.reduce((a, b) => (a.days_behind > b.days_behind ? a : b));
  return (
    <div style={{ fontSize: 8, color: COLORS.textDim, marginBottom: 8 }}>
      Data: {freshest.latest?.slice(0, 7)} to {stalest.latest?.slice(0, 7)}
      {' | '}{entries.reduce((s, e) => s + e.n_obs, 0).toLocaleString()} total obs
      {stalest.days_behind > 180 && (
        <span style={{ color: COLORS.amber, marginLeft: 8 }}>
          Stalest series: {stalest.days_behind}d behind (BIS quarterly lag)
        </span>
      )}
    </div>
  );
}

function CreditPanel({ data }) {
  if (!data) return null;
  const { indicators, country_names: cn, as_of: asOf } = data;
  return (
    <div>
      <MetaBar asOf={asOf} />
      <MultiLineChart data={indicators?.credit_to_gdp} title="TOTAL CREDIT TO NON-FINANCIAL SECTOR (% of GDP)"
        yLabel="% GDP" countries={Object.keys(indicators?.credit_to_gdp || {})} countryNames={cn} />
      <MultiLineChart data={indicators?.credit_gdp_gap} title="CREDIT-TO-GDP GAP (pp deviation from trend)"
        yLabel="pp" countries={Object.keys(indicators?.credit_gdp_gap || {})} countryNames={cn} />
      <MultiLineChart data={indicators?.debt_service_ratio} title="DEBT SERVICE RATIO — PRIVATE NON-FINANCIAL (%)"
        yLabel="%" countries={Object.keys(indicators?.debt_service_ratio || {})} countryNames={cn} />
      {indicators?.debt_service_ratio_hh && Object.keys(indicators.debt_service_ratio_hh).length > 0 && (
        <MultiLineChart data={indicators.debt_service_ratio_hh} title="DEBT SERVICE RATIO — HOUSEHOLDS (%)"
          yLabel="%" countries={Object.keys(indicators.debt_service_ratio_hh)} countryNames={cn} />
      )}
    </div>
  );
}

function FXPanel({ data }) {
  if (!data) return null;
  const { indicators, country_names: cn, as_of: asOf } = data;
  return (
    <div>
      <MetaBar asOf={asOf} />
      <MultiLineChart data={indicators?.neer_broad} title="NOMINAL EFFECTIVE EXCHANGE RATE — BROAD (index, 2020=100)"
        yLabel="Index" countries={Object.keys(indicators?.neer_broad || {})} countryNames={cn} />
      <MultiLineChart data={indicators?.reer_broad} title="REAL EFFECTIVE EXCHANGE RATE — BROAD (index, 2020=100)"
        yLabel="Index" countries={Object.keys(indicators?.reer_broad || {})} countryNames={cn} />
      <MultiLineChart data={indicators?.policy_rate} title="CENTRAL BANK POLICY RATES (%)"
        yLabel="%" countries={Object.keys(indicators?.policy_rate || {})} countryNames={cn} />
    </div>
  );
}

function PropertyPanel({ data }) {
  if (!data) return null;
  const { indicators, country_names: cn, as_of: asOf } = data;
  return (
    <div>
      <MetaBar asOf={asOf} />
      <MultiLineChart data={indicators?.residential_nominal} title="RESIDENTIAL PROPERTY PRICES — NOMINAL (index, 2010=100)"
        yLabel="Index" countries={Object.keys(indicators?.residential_nominal || {})} countryNames={cn} />
      <MultiLineChart data={indicators?.residential_real} title="RESIDENTIAL PROPERTY PRICES — REAL (YoY %)"
        yLabel="%" countries={Object.keys(indicators?.residential_real || {})} countryNames={cn} />
    </div>
  );
}

const PANELS = { credit: CreditPanel, fx: FXPanel, property: PropertyPanel };

export default function BISExplorerTab() {
  const [subTab, setSubTab] = useState('CREDIT & DEBT');
  const [groupData, setGroupData] = useState({});
  const [loading, setLoading] = useState({});

  const loadGroup = useCallback(async (tab, force = false) => {
    const group = GROUP_MAP[tab];
    if (!force && groupData[group]) return;
    setLoading(prev => ({ ...prev, [group]: true }));
    try {
      const r = await getBisGroup(group, force);
      if (r && !r.error) setGroupData(prev => ({ ...prev, [group]: r }));
    } catch (e) { console.error(e); }
    finally { setLoading(prev => ({ ...prev, [group]: false })); }
  }, [groupData]);

  const handleTabChange = (tab) => {
    setSubTab(tab);
    loadGroup(tab);
  };

  // Load first tab on mount
  React.useEffect(() => { loadGroup('CREDIT & DEBT'); }, []);

  const group = GROUP_MAP[subTab];
  const Panel = PANELS[group];
  const isLoading = loading[group];
  const data = groupData[group];

  return (
    <div style={{ padding: '8px 0', fontFamily: FONT }}>
      {/* Sub-tab bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, borderBottom: `1px solid ${COLORS.cardBorder}`, marginBottom: 10 }}>
        {SUB_TABS.map(tab => (
          <button key={tab} onClick={() => handleTabChange(tab)} style={{
            background: 'none', border: 'none', padding: '8px 16px', cursor: 'pointer',
            borderBottom: subTab === tab ? `2px solid ${COLORS.amber}` : '2px solid transparent',
            color: subTab === tab ? COLORS.amber : COLORS.textMuted,
            fontFamily: FONT, fontSize: 11, letterSpacing: 1, fontWeight: subTab === tab ? 'bold' : 'normal',
          }}>{tab}</button>
        ))}
        <div style={{ flex: 1 }} />
        <button onClick={() => loadGroup(subTab, true)} disabled={isLoading}
          style={{ padding: '3px 12px', background: 'none', color: COLORS.cyan,
            border: `1px solid ${COLORS.cyan}44`, fontFamily: FONT, fontSize: 10, cursor: 'pointer', marginRight: 4 }}>
          {isLoading ? 'LOADING...' : 'REFRESH'}
        </button>
        {data?.from_cache && (
          <span style={{ color: COLORS.amber, fontSize: 8, marginRight: 8 }}>(cached)</span>
        )}
      </div>

      {/* Content */}
      {isLoading && !data && (
        <div style={{ padding: 20, color: COLORS.textMuted, fontSize: 11 }}>
          Loading BIS {group} data...
        </div>
      )}

      {data && Panel && <Panel data={data} />}

      {!data && !isLoading && (
        <div style={{ padding: 20, color: COLORS.textDim, fontSize: 10 }}>
          Select a tab above to load BIS data. Data is fetched on-demand and cached for 24 hours.
        </div>
      )}
    </div>
  );
}
