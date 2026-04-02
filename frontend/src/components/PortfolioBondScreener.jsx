import React, { useState, useEffect, useMemo } from 'react';
import { COLORS, FONT } from '../utils/theme';
import { uploadBonds, getBonds } from '../utils/api';

const RATING_OPTIONS = ['AAA','AA+','AA','AA-','A+','A','A-','BBB+','BBB','BBB-','BB+','BB','BB-','B+','B','B-','CCC+','CCC','CCC-','CC','C','D'];
const RATING_NUM = {};
RATING_OPTIONS.forEach((r, i) => { RATING_NUM[r] = i + 1; });

export default function PortfolioBondScreener({ onAddToPortfolio, portfolio }) {
  const [bonds, setBonds] = useState([]);
  const [summary, setSummary] = useState(null);
  const [totalUniverse, setTotalUniverse] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [uploaded, setUploaded] = useState(false);
  const [sortCol, setSortCol] = useState('ytm');
  const [sortAsc, setSortAsc] = useState(false);
  const [selectedBond, setSelectedBond] = useState(null);

  // Check if bonds already loaded on backend (persists across tab switches)
  useEffect(() => {
    getBonds({}).then(result => {
      if (result.total_universe > 0) {
        setBonds(result.bonds || []);
        setTotalUniverse(result.total_universe);
        setUploaded(true);
      }
    }).catch(() => {});
  }, []);

  // Filters
  const [search, setSearch] = useState('');
  const [currency, setCurrency] = useState('');
  const [ratingMin, setRatingMin] = useState('');
  const [ratingMax, setRatingMax] = useState('');
  const [maturityMin, setMaturityMin] = useState('');
  const [maturityMax, setMaturityMax] = useState('');
  const [durationMin, setDurationMin] = useState('');
  const [durationMax, setDurationMax] = useState('');
  const [ytmMin, setYtmMin] = useState('');
  const [ytmMax, setYtmMax] = useState('');
  const [oasMin, setOasMin] = useState('');
  const [oasMax, setOasMax] = useState('');
  const [couponMin, setCouponMin] = useState('');
  const [couponMax, setCouponMax] = useState('');

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const result = await uploadBonds(file);
      setSummary(result.summary);
      setUploaded(true);
      fetchBonds();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchBonds = async () => {
    setLoading(true);
    try {
      const filters = {};
      if (search) filters.search = search;
      if (currency) filters.currencies = currency;
      if (ratingMin) filters.rating_min = RATING_NUM[ratingMin];
      if (ratingMax) filters.rating_max = RATING_NUM[ratingMax];
      if (maturityMin) filters.maturity_min = parseFloat(maturityMin);
      if (maturityMax) filters.maturity_max = parseFloat(maturityMax);
      if (durationMin) filters.duration_min = parseFloat(durationMin);
      if (durationMax) filters.duration_max = parseFloat(durationMax);
      if (ytmMin) filters.ytm_min = parseFloat(ytmMin);
      if (ytmMax) filters.ytm_max = parseFloat(ytmMax);
      if (oasMin) filters.oas_min = parseFloat(oasMin);
      if (oasMax) filters.oas_max = parseFloat(oasMax);
      if (couponMin) filters.coupon_min = parseFloat(couponMin);
      if (couponMax) filters.coupon_max = parseFloat(couponMax);

      const result = await getBonds(filters);
      setBonds(result.bonds || []);
      setTotalUniverse(result.total_universe || 0);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (uploaded) fetchBonds();
  }, [search, currency, ratingMin, ratingMax, maturityMin, maturityMax,
      durationMin, durationMax, ytmMin, ytmMax, oasMin, oasMax, couponMin, couponMax]);

  const sorted = useMemo(() => {
    const s = [...bonds];
    s.sort((a, b) => {
      const va = a[sortCol] ?? (sortAsc ? Infinity : -Infinity);
      const vb = b[sortCol] ?? (sortAsc ? Infinity : -Infinity);
      if (typeof va === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
      return sortAsc ? va - vb : vb - va;
    });
    return s;
  }, [bonds, sortCol, sortAsc]);

  const handleSort = (col) => {
    if (sortCol === col) setSortAsc(!sortAsc);
    else { setSortCol(col); setSortAsc(false); }
  };

  const inPortfolio = (id) => portfolio.some(p => p.id === id);

  const inputStyle = {
    padding: '3px 6px', background: COLORS.bg, border: `1px solid ${COLORS.cardBorder}`,
    color: COLORS.white, fontFamily: FONT, fontSize: 10, width: 60, outline: 'none',
  };

  const columns = [
    { key: 'issuer_name', label: 'ISSUER', width: 170, align: 'left' },
    { key: 'isin', label: 'ISIN', width: 110, align: 'left' },
    { key: 'issuer_industry', label: 'INDUSTRY', width: 100, align: 'left' },
    { key: 'coupon', label: 'CPN', width: 45, fmt: v => v?.toFixed(2) },
    { key: 'maturity', label: 'MATURITY', width: 80 },
    { key: 'currency', label: 'CCY', width: 35 },
    { key: 'rating', label: 'RATING', width: 42 },
    { key: 'ytm', label: 'YTM', width: 50, fmt: v => v?.toFixed(2) + '%' },
    { key: 'ytw', label: 'YTW', width: 50, fmt: v => v?.toFixed(2) + '%' },
    { key: 'oas_spread', label: 'OAS', width: 50, fmt: v => v?.toFixed(0) + 'bp' },
    { key: 'g_spread', label: 'G-SPR', width: 50, fmt: v => v?.toFixed(0) + 'bp' },
    { key: 'duration', label: 'DUR', width: 42, fmt: v => v?.toFixed(1) },
    { key: 'bid_ask_spread', label: 'BID-ASK', width: 55, fmt: v => v?.toFixed(2) },
    { key: 'default_probability', label: 'DEF%', width: 55, fmt: v => v ? (v * 100).toFixed(2) + '%' : '—' },
  ];

  return (
    <div style={{ fontFamily: FONT, color: COLORS.white }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: COLORS.amber, letterSpacing: 2, fontWeight: 'bold' }}>
          BOND SCREENER
        </h2>
        {uploaded && (
          <span style={{ fontSize: 11, color: COLORS.textMuted }}>
            {bonds.length} of {totalUniverse} bonds match filters
          </span>
        )}
      </div>

      {/* Upload zone */}
      {!uploaded && (
        <div style={{
          border: `2px dashed ${COLORS.cardBorder}`, padding: 40, textAlign: 'center',
          marginBottom: 16, background: COLORS.card,
        }}>
          <div style={{ color: COLORS.amber, fontSize: 14, marginBottom: 8 }}>
            Upload Bond Universe CSV
          </div>
          <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 16 }}>
            Semicolon or tab-delimited Bloomberg export CSV
          </div>
          <label style={{
            padding: '8px 20px', background: COLORS.amber, color: COLORS.bg,
            fontFamily: FONT, fontSize: 12, cursor: 'pointer', letterSpacing: 1,
          }}>
            SELECT FILE
            <input type="file" accept=".csv,.txt,.tsv" onChange={handleUpload}
              style={{ display: 'none' }} />
          </label>
        </div>
      )}

      {loading && <div style={{ padding: 20, color: COLORS.amber, fontSize: 12 }}>Loading...</div>}
      {error && <div style={{ padding: 10, color: COLORS.red, fontSize: 11 }}>Error: {error}</div>}

      {/* Filters */}
      {uploaded && (
        <>
          <div style={{
            display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12,
            padding: 10, background: COLORS.card, border: `1px solid ${COLORS.cardBorder}`,
            alignItems: 'center',
          }}>
            <input placeholder="Search issuer/ticker..." value={search} onChange={e => setSearch(e.target.value)}
              style={{ ...inputStyle, width: 160 }} />
            <select value={currency} onChange={e => setCurrency(e.target.value)}
              style={{ ...inputStyle, width: 70 }}>
              <option value="">All CCY</option>
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
            </select>
            <span style={{ fontSize: 9, color: COLORS.textMuted }}>RATING:</span>
            <select value={ratingMin} onChange={e => setRatingMin(e.target.value)} style={{ ...inputStyle, width: 55 }}>
              <option value="">Min</option>
              {RATING_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            <span style={{ fontSize: 9, color: COLORS.textMuted }}>to</span>
            <select value={ratingMax} onChange={e => setRatingMax(e.target.value)} style={{ ...inputStyle, width: 55 }}>
              <option value="">Max</option>
              {RATING_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            <span style={{ fontSize: 9, color: COLORS.textMuted }}>DUR:</span>
            <input value={durationMin} onChange={e => setDurationMin(e.target.value)} placeholder="0" style={inputStyle} />
            <span style={{ fontSize: 9, color: COLORS.textMuted }}>-</span>
            <input value={durationMax} onChange={e => setDurationMax(e.target.value)} placeholder="5" style={inputStyle} />
            <span style={{ fontSize: 9, color: COLORS.textMuted }}>YTM:</span>
            <input value={ytmMin} onChange={e => setYtmMin(e.target.value)} placeholder="Min" style={inputStyle} />
            <span style={{ fontSize: 9, color: COLORS.textMuted }}>-</span>
            <input value={ytmMax} onChange={e => setYtmMax(e.target.value)} placeholder="Max" style={inputStyle} />
            <span style={{ fontSize: 9, color: COLORS.textMuted }}>OAS:</span>
            <input value={oasMin} onChange={e => setOasMin(e.target.value)} placeholder="Min" style={inputStyle} />
            <span style={{ fontSize: 9, color: COLORS.textMuted }}>-</span>
            <input value={oasMax} onChange={e => setOasMax(e.target.value)} placeholder="Max" style={inputStyle} />
            <button onClick={() => { setSearch(''); setCurrency(''); setRatingMin(''); setRatingMax('');
              setDurationMin(''); setDurationMax(''); setYtmMin(''); setYtmMax('');
              setOasMin(''); setOasMax(''); setCouponMin(''); setCouponMax(''); }}
              style={{ padding: '3px 8px', background: 'none', color: COLORS.textMuted,
                border: `1px solid ${COLORS.cardBorder}`, fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
              RESET
            </button>
            <label style={{ padding: '3px 8px', background: COLORS.amber, color: COLORS.bg,
              fontFamily: FONT, fontSize: 9, cursor: 'pointer' }}>
              NEW CSV
              <input type="file" accept=".csv,.txt,.tsv" onChange={handleUpload} style={{ display: 'none' }} />
            </label>
          </div>

          {/* Results table */}
          <div style={{ overflowX: 'auto', background: COLORS.card, border: `1px solid ${COLORS.cardBorder}` }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: FONT, minWidth: 1000 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${COLORS.cardBorder}` }}>
                  <th style={{ padding: '5px 6px', color: COLORS.textMuted, fontSize: 9, textAlign: 'center', width: 50 }}>ADD</th>
                  {columns.map(c => (
                    <th key={c.key} onClick={() => handleSort(c.key)} style={{
                      padding: '5px 6px', color: sortCol === c.key ? COLORS.amber : COLORS.textMuted,
                      fontSize: 9, textAlign: c.align || 'right', cursor: 'pointer', width: c.width,
                    }}>
                      {c.label}{sortCol === c.key ? (sortAsc ? ' ▲' : ' ▼') : ''}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((bond, i) => (
                  <tr key={bond.id || i} onClick={() => setSelectedBond(bond)}
                    style={{
                      borderBottom: `1px solid ${COLORS.cardBorder}22`,
                      background: i % 2 === 0 ? COLORS.card : 'transparent',
                      cursor: 'pointer',
                    }}>
                    <td style={{ padding: '4px 6px', textAlign: 'center' }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); onAddToPortfolio(bond); }}
                        disabled={inPortfolio(bond.id)}
                        style={{
                          padding: '2px 6px', fontSize: 9, fontFamily: FONT,
                          background: inPortfolio(bond.id) ? COLORS.textMuted : COLORS.green,
                          color: COLORS.bg, border: 'none', cursor: inPortfolio(bond.id) ? 'default' : 'pointer',
                          opacity: inPortfolio(bond.id) ? 0.4 : 1,
                        }}>
                        {inPortfolio(bond.id) ? '✓' : '+'}
                      </button>
                    </td>
                    {columns.map(c => {
                      const val = bond[c.key];
                      const display = val == null ? '—' : (c.fmt ? c.fmt(val) : val);
                      return (
                        <td key={c.key} style={{
                          padding: '4px 6px', textAlign: c.align || 'right',
                          color: c.key === 'issuer_name' ? COLORS.white : COLORS.textSecondary,
                          fontWeight: c.key === 'issuer_name' ? 'bold' : 'normal',
                          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                          maxWidth: c.width,
                        }}>
                          {display}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Bond detail popup */}
      {selectedBond && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }} onClick={() => setSelectedBond(null)}>
          <div style={{
            background: '#111', border: `1px solid ${COLORS.amber}44`, padding: 24, width: 500,
            fontFamily: FONT, maxHeight: '80vh', overflowY: 'auto',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <h3 style={{ color: COLORS.amber, fontSize: 14, margin: 0 }}>{selectedBond.issuer_name}</h3>
              <button onClick={() => setSelectedBond(null)} style={{
                background: 'none', border: 'none', color: COLORS.textMuted, fontSize: 18, cursor: 'pointer',
              }}>×</button>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <tbody>
                {Object.entries(selectedBond).filter(([k]) => k !== 'id').map(([key, val]) => (
                  <tr key={key} style={{ borderBottom: `1px solid ${COLORS.cardBorder}22` }}>
                    <td style={{ padding: '4px 8px', color: COLORS.textMuted, width: '40%' }}>{key}</td>
                    <td style={{ padding: '4px 8px', color: COLORS.white }}>
                      {val == null ? '—' : typeof val === 'number' ? val.toLocaleString(undefined, { maximumFractionDigits: 6 }) : String(val)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button onClick={() => { onAddToPortfolio(selectedBond); setSelectedBond(null); }}
              disabled={inPortfolio(selectedBond.id)}
              style={{
                marginTop: 12, padding: '8px 20px', width: '100%',
                background: inPortfolio(selectedBond.id) ? COLORS.textMuted : COLORS.green,
                color: COLORS.bg, border: 'none', fontFamily: FONT, fontSize: 12, cursor: 'pointer',
              }}>
              {inPortfolio(selectedBond.id) ? 'ALREADY IN PORTFOLIO' : 'ADD TO PORTFOLIO'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
