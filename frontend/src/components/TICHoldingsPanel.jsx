import React, { useState, useEffect, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ComposedChart, Area, ReferenceLine,
} from 'recharts';
import { COLORS, FONT } from '../utils/theme';
import { getTicHoldings } from '../utils/api';

const RANGES = [
  { label: '5Y', years: 5 }, { label: '10Y', years: 10 },
  { label: '15Y', years: 15 }, { label: 'ALL', years: 0 },
];

const COUNTRY_COLORS = [
  '#ffaa00', '#ff4444', '#00e5ff', '#00ff88', '#8844cc',
  '#ff80ab', '#448aff', '#ff9100', '#00cccc', '#cc44aa',
  '#66ff66', '#ff6666', '#6699ff', '#ffcc00', '#ff44aa',
];

const DEFAULT_SELECTED = ['Japan', 'China, Mainland', 'United Kingdom', 'Belgium', 'Canada'];

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '8px 12px', fontFamily: FONT, fontSize: 11 }}>
      <div style={{ color: COLORS.amber, marginBottom: 4 }}>{label}</div>
      {payload.filter(p => p.value != null).sort((a, b) => b.value - a.value).map(p => (
        <div key={p.dataKey} style={{ color: p.color, display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span>{p.dataKey}</span>
          <span>{p.value?.toLocaleString(undefined, { maximumFractionDigits: 1 })}B</span>
        </div>
      ))}
    </div>
  );
};

export default function TICHoldingsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [rangeYears, setRangeYears] = useState(10);
  const [selected, setSelected] = useState(DEFAULT_SELECTED);
  const [search, setSearch] = useState('');
  const [indexMode, setIndexMode] = useState(false);
  const [sortCol, setSortCol] = useState('latest');
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTicHoldings({ rangeYears })
      .then(r => { if (!cancelled) setData(r); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [rangeYears]);

  // Build sorted country list from summary
  const countryList = useMemo(() => {
    if (!data?.summary) return [];
    return data.summary.filter(s => s.country !== 'All Other');
  }, [data]);

  // Filter by search
  const filteredCountries = useMemo(() => {
    if (!search) return countryList;
    const q = search.toLowerCase();
    return countryList.filter(c => c.country.toLowerCase().includes(q));
  }, [countryList, search]);

  // Build chart data — merge selected countries into one array
  const chartData = useMemo(() => {
    if (!data?.countries) return [];
    const allDates = new Set();
    selected.forEach(name => {
      const c = data.countries[name];
      if (c) c.dates.forEach(d => allDates.add(d));
    });
    const dates = [...allDates].sort();

    return dates.map(date => {
      const entry = { date };
      selected.forEach(name => {
        const c = data.countries[name];
        if (c) {
          const idx = c.dates.indexOf(date);
          if (idx >= 0) entry[name] = c.values[idx];
        }
      });
      return entry;
    });
  }, [data, selected]);

  // Index mode: rebase to 100
  const indexedData = useMemo(() => {
    if (!indexMode || !chartData.length) return chartData;
    const bases = {};
    selected.forEach(name => {
      for (const row of chartData) {
        if (row[name] != null) { bases[name] = row[name]; break; }
      }
    });
    return chartData.map(row => {
      const entry = { date: row.date };
      selected.forEach(name => {
        if (row[name] != null && bases[name]) {
          entry[name] = (row[name] / bases[name]) * 100;
        }
      });
      return entry;
    });
  }, [chartData, indexMode, selected]);

  // Grand total chart data
  const totalChartData = useMemo(() => {
    if (!data?.aggregates) return [];
    const total = data.aggregates['Grand Total'];
    const official = data.aggregates['Official'];
    if (!total) return [];

    return total.dates.map((date, i) => {
      const t = total.values[i];
      const offIdx = official?.dates.indexOf(date);
      const o = offIdx >= 0 ? official.values[offIdx] : null;
      return { date, total: t, official: o, private: (t && o) ? t - o : null };
    });
  }, [data]);

  // Sorted summary for table
  const sortedSummary = useMemo(() => {
    if (!data?.summary) return [];
    const s = [...data.summary].filter(x => x.country !== 'All Other');
    s.sort((a, b) => {
      const va = a[sortCol] ?? 0;
      const vb = b[sortCol] ?? 0;
      return sortAsc ? va - vb : vb - va;
    });
    return s.slice(0, 15);
  }, [data, sortCol, sortAsc]);

  const btn = (active, onClick, label) => (
    <button key={label} onClick={onClick} style={{
      padding: '3px 10px', fontFamily: FONT, fontSize: 11, cursor: 'pointer',
      backgroundColor: active ? COLORS.amber : COLORS.bg,
      color: active ? COLORS.bg : COLORS.textMuted,
      border: `1px solid ${active ? COLORS.amber : COLORS.cardBorder}`,
    }}>{label}</button>
  );

  const toggle = (name) => {
    setSelected(prev => prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]);
  };

  const quickSelect = (n) => {
    if (n === 0) setSelected([]);
    else setSelected(countryList.slice(0, n).map(c => c.country));
  };

  const handleSort = (col) => {
    if (sortCol === col) setSortAsc(!sortAsc);
    else { setSortCol(col); setSortAsc(false); }
  };

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: COLORS.amber, letterSpacing: 2, fontWeight: 'bold' }}>
          MAJOR FOREIGN HOLDERS OF U.S. TREASURIES
        </h2>
        <span style={{ fontSize: 11, color: COLORS.textMuted }}>
          {data?.metadata?.date_range?.[0]} to {data?.metadata?.date_range?.[1]} | {data?.metadata?.countries_count} countries
        </span>
      </div>

      {loading && <div style={{ padding: 20, color: COLORS.amber, fontSize: 12 }}>Loading TIC data...</div>}
      {error && <div style={{ padding: 20, color: COLORS.red, fontSize: 12 }}>Error: {error}</div>}

      {!loading && data && (
        <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 12 }}>
          {/* Left sidebar — Country selector */}
          <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 10, maxHeight: 600, overflowY: 'auto' }}>
            <input
              type="text" placeholder="Search..."
              value={search} onChange={e => setSearch(e.target.value)}
              style={{ width: '100%', padding: '4px 8px', background: COLORS.bg, border: `1px solid ${COLORS.cardBorder}`, color: COLORS.white, fontFamily: FONT, fontSize: 11, marginBottom: 8, outline: 'none' }}
            />
            <div style={{ display: 'flex', gap: 3, marginBottom: 8, flexWrap: 'wrap' }}>
              {[['TOP 5', 5], ['TOP 10', 10], ['ALL', 99], ['CLEAR', 0]].map(([label, n]) => (
                <button key={label} onClick={() => quickSelect(n)} style={{
                  padding: '2px 6px', fontSize: 9, fontFamily: FONT, cursor: 'pointer',
                  background: COLORS.bg, color: COLORS.textMuted, border: `1px solid ${COLORS.cardBorder}`,
                }}>{label}</button>
              ))}
            </div>
            {filteredCountries.map((c, i) => (
              <div key={c.country} onClick={() => toggle(c.country)} style={{
                display: 'flex', alignItems: 'center', gap: 6, padding: '3px 4px', cursor: 'pointer',
                background: selected.includes(c.country) ? `${COLORS.amber}11` : 'transparent',
                fontSize: 10,
              }}>
                <div style={{
                  width: 10, height: 10, border: `1px solid ${COLORS.cardBorder}`,
                  background: selected.includes(c.country) ? COUNTRY_COLORS[selected.indexOf(c.country) % COUNTRY_COLORS.length] : 'transparent',
                }} />
                <span style={{ flex: 1, color: COLORS.white }}>{c.country}</span>
                <span style={{ color: COLORS.textMuted }}>${c.latest}B</span>
              </div>
            ))}
          </div>

          {/* Right — Charts */}
          <div>
            {/* Controls */}
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 8 }}>
              <span style={{ color: COLORS.textMuted, fontSize: 11 }}>RANGE:</span>
              {RANGES.map(r => btn(rangeYears === r.years, () => setRangeYears(r.years), r.label))}
              <span style={{ color: COLORS.textMuted, fontSize: 11, margin: '0 8px' }}>|</span>
              <button onClick={() => setIndexMode(!indexMode)} style={{
                padding: '3px 10px', fontFamily: FONT, fontSize: 11, cursor: 'pointer',
                background: indexMode ? COLORS.cyan : COLORS.bg,
                color: indexMode ? COLORS.bg : COLORS.textMuted,
                border: `1px solid ${indexMode ? COLORS.cyan : COLORS.cardBorder}`,
              }}>INDEX MODE {indexMode ? 'ON' : 'OFF'}</button>
            </div>

            {/* Main holdings chart */}
            <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12, marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8 }}>
                HOLDINGS BY COUNTRY {indexMode ? '(INDEXED, BASE=100)' : '($B)'}
              </div>
              <ResponsiveContainer width="100%" height={350}>
                <LineChart data={indexedData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <XAxis dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }} axisLine={{ stroke: COLORS.cardBorder }} tickLine={false} interval={Math.max(1, Math.floor(indexedData.length / 12))} angle={-45} textAnchor="end" height={45} />
                  <YAxis tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} axisLine={false} tickLine={false} tickFormatter={v => indexMode ? v.toFixed(0) : `${v}B`} width={50} />
                  <Tooltip content={<CustomTooltip />} />
                  {selected.map((name, i) => (
                    <Line key={name} dataKey={name} stroke={COUNTRY_COLORS[i % COUNTRY_COLORS.length]} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
              {/* Legend */}
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 8 }}>
                {selected.map((name, i) => (
                  <div key={name} onClick={() => toggle(name)} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, cursor: 'pointer' }}>
                    <div style={{ width: 14, height: 3, background: COUNTRY_COLORS[i % COUNTRY_COLORS.length] }} />
                    <span style={{ color: COUNTRY_COLORS[i % COUNTRY_COLORS.length] }}>{name}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Grand Total chart */}
            {totalChartData.length > 0 && (
              <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12, marginBottom: 12 }}>
                <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8 }}>
                  TOTAL FOREIGN HOLDINGS & COMPOSITION
                </div>
                <ResponsiveContainer width="100%" height={220}>
                  <ComposedChart data={totalChartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                    <XAxis dataKey="date" tick={{ fill: COLORS.textMuted, fontSize: 9, fontFamily: FONT }} axisLine={{ stroke: COLORS.cardBorder }} tickLine={false} interval={Math.max(1, Math.floor(totalChartData.length / 10))} angle={-45} textAnchor="end" height={40} />
                    <YAxis tick={{ fill: COLORS.textMuted, fontSize: 10, fontFamily: FONT }} axisLine={false} tickLine={false} tickFormatter={v => `${(v/1000).toFixed(1)}T`} width={45} />
                    <Tooltip content={({ active, payload, label }) => {
                      if (!active || !payload?.length) return null;
                      return (
                        <div style={{ background: '#111', border: `1px solid ${COLORS.cardBorder}`, padding: '6px 10px', fontFamily: FONT, fontSize: 11 }}>
                          <div style={{ color: COLORS.amber }}>{label}</div>
                          {payload.map(p => (
                            <div key={p.dataKey} style={{ color: p.color }}>{p.dataKey}: ${p.value?.toLocaleString()}B</div>
                          ))}
                        </div>
                      );
                    }} />
                    <Area dataKey="official" stackId="1" fill={COLORS.cyan} fillOpacity={0.3} stroke={COLORS.cyan} strokeWidth={1} />
                    <Area dataKey="private" stackId="1" fill={COLORS.purple} fillOpacity={0.3} stroke={COLORS.purple} strokeWidth={1} />
                    <Line dataKey="total" stroke={COLORS.amber} strokeWidth={2} dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
                <div style={{ display: 'flex', gap: 16, fontSize: 10, marginTop: 4 }}>
                  <span><span style={{ color: COLORS.amber }}>—</span> Grand Total</span>
                  <span><span style={{ color: COLORS.cyan }}>■</span> Official</span>
                  <span><span style={{ color: COLORS.purple }}>■</span> Private</span>
                </div>
              </div>
            )}

            {/* Holdings change table */}
            <div style={{ background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`, padding: 12 }}>
              <div style={{ fontSize: 11, color: COLORS.amber, marginBottom: 8 }}>HOLDINGS CHANGE BY COUNTRY</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: FONT }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                    {[
                      { key: 'country', label: 'COUNTRY', align: 'left' },
                      { key: 'latest', label: 'CURRENT ($B)' },
                      { key: 'change_1m', label: '1M CHG' },
                      { key: 'pct_1m', label: '1M %' },
                      { key: 'change_12m', label: '12M CHG' },
                      { key: 'pct_12m', label: '12M %' },
                      { key: 'all_time_high', label: 'ATH ($B)' },
                      { key: 'ath_date', label: 'ATH DATE' },
                    ].map(col => (
                      <th key={col.key} onClick={() => handleSort(col.key)} style={{
                        padding: '4px 6px', color: sortCol === col.key ? COLORS.amber : COLORS.textMuted,
                        fontSize: 10, textAlign: col.align || 'right', fontWeight: 'normal', cursor: 'pointer',
                      }}>
                        {col.label}{sortCol === col.key ? (sortAsc ? ' ▲' : ' ▼') : ''}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedSummary.map((s, i) => (
                    <tr key={s.country} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                      <td style={{ padding: '4px 6px', color: COLORS.white }}>{s.country}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 'bold' }}>{s.latest?.toLocaleString()}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: (s.change_1m || 0) >= 0 ? COLORS.green : COLORS.red }}>
                        {s.change_1m != null ? `${s.change_1m >= 0 ? '+' : ''}${s.change_1m}` : '—'}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: (s.pct_1m || 0) >= 0 ? COLORS.green : COLORS.red }}>
                        {s.pct_1m != null ? `${s.pct_1m >= 0 ? '+' : ''}${s.pct_1m}%` : '—'}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: (s.change_12m || 0) >= 0 ? COLORS.green : COLORS.red }}>
                        {s.change_12m != null ? `${s.change_12m >= 0 ? '+' : ''}${s.change_12m}` : '—'}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: (s.pct_12m || 0) >= 0 ? COLORS.green : COLORS.red }}>
                        {s.pct_12m != null ? `${s.pct_12m >= 0 ? '+' : ''}${s.pct_12m}%` : '—'}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: COLORS.textSecondary }}>{s.all_time_high?.toLocaleString()}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: COLORS.textMuted }}>{s.ath_date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
