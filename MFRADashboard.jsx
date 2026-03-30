import React, { useState, useMemo } from 'react';

// ─── CONSTANTS ───────────────────────────────────────────────
var COLORS = {
  bg: '#060911',
  card: '#0b1120',
  border: '#152035',
  green: '#34d399',
  red: '#fb7185',
  blue: '#38bdf8',
  purple: '#a78bfa',
  amber: '#fbbf24',
  white: '#edf1f7',
  muted: '#8892a4',
  rowAlt: '#0d1526',
};

var FONT = "'IBM Plex Mono', 'JetBrains Mono', 'Fira Code', monospace";

var TAB_NAMES = ['Data Input', 'Overview', 'Nominal Performance', 'Risk-Adjusted', 'Alpha Map', 'Behavioral', 'Insights'];

var APPROX_FX = { EUR: 1.08, JPY: 0.00667, SEK: 0.096, CHF: 1.12, GBP: 1.27, USD: 1.0 };

// ─── STYLE HELPERS ───────────────────────────────────────────
function s() {
  var result = {};
  for (var i = 0; i < arguments.length; i++) {
    var obj = arguments[i];
    if (obj) {
      var keys = Object.keys(obj);
      for (var k = 0; k < keys.length; k++) {
        result[keys[k]] = obj[keys[k]];
      }
    }
  }
  return result;
}

var baseStyle = {
  fontFamily: FONT,
  color: COLORS.white,
  backgroundColor: COLORS.bg,
  minHeight: '100vh',
  padding: '24px',
  boxSizing: 'border-box',
};

var cardStyle = {
  backgroundColor: COLORS.card,
  border: '1px solid ' + COLORS.border,
  borderRadius: '8px',
  padding: '16px',
};

var kpiLabelStyle = {
  fontSize: '10px',
  letterSpacing: '1.5px',
  textTransform: 'uppercase',
  color: COLORS.muted,
  marginBottom: '4px',
};

var kpiValueStyle = {
  fontSize: '24px',
  fontWeight: '700',
  lineHeight: '1.2',
};

var kpiSubStyle = {
  fontSize: '11px',
  color: COLORS.muted,
  marginTop: '4px',
};

var tableHeaderStyle = {
  padding: '8px 12px',
  textAlign: 'left',
  fontSize: '10px',
  letterSpacing: '1px',
  textTransform: 'uppercase',
  color: COLORS.muted,
  borderBottom: '1px solid ' + COLORS.border,
  cursor: 'pointer',
  userSelect: 'none',
  whiteSpace: 'nowrap',
};

var tableCellStyle = {
  padding: '8px 12px',
  fontSize: '12px',
  whiteSpace: 'nowrap',
};

// ─── PARSING ─────────────────────────────────────────────────
function cleanNum(val) {
  if (!val || val.trim() === '' || val.trim() === '#N/A') return null;
  var cleaned = val.replace(/%/g, '').replace(/\s/g, '').replace(/,/g, '');
  var num = parseFloat(cleaned);
  if (isNaN(num)) return null;
  return num;
}

function cleanPct(val) {
  if (!val || val.trim() === '' || val.trim() === '#N/A') return null;
  var cleaned = val.replace(/%/g, '').replace(/\s/g, '').replace(/,/g, '');
  var num = parseFloat(cleaned);
  if (isNaN(num)) return null;
  return num / 100;
}

function cleanTicker(val) {
  if (!val) return '';
  return val.replace(/\s*Equity\s*/gi, '').trim();
}

function detectCurrency(sellCcyCol, buyCcyCol) {
  var ccy = (sellCcyCol || '').trim();
  if (ccy && ccy.length >= 2 && ccy.length <= 4) return ccy.toUpperCase();
  ccy = (buyCcyCol || '').trim();
  if (ccy && ccy.length >= 2 && ccy.length <= 4) return ccy.toUpperCase();
  return 'USD';
}

function daysBetween(d1, d2) {
  var a = new Date(d1);
  var b = new Date(d2);
  return Math.round((b - a) / (1000 * 60 * 60 * 24));
}

function parseData(raw) {
  var lines = raw.split('\n').filter(function(l) { return l.trim().length > 0; });
  if (lines.length < 2) return [];

  var lots = [];
  for (var i = 1; i < lines.length; i++) {
    var cols = lines[i].split('\t');
    if (cols.length < 10) continue;

    var ticker = cleanTicker(cols[0]);
    if (!ticker) continue;

    var buyCcy = (cols[1] || '').trim();
    var tradeDate = (cols[2] || '').trim();
    var sellDate = (cols[3] || '').trim();
    var costAmount = cleanNum(cols[4]);
    var sellCcy = (cols[5] || '').trim();
    var sellAmount = cleanNum(cols[6]);
    var pnlLocal = cleanNum(cols[7]);
    var pnlUSD = cleanNum(cols[8]);
    var marketBeta = cleanNum(cols[9]);
    var indexName = (cols[10] || '').trim();
    var indexShort = (cols[11] || '').trim();
    var indexReturn = cleanPct(cols[12]);
    var sectorBeta = cleanNum(cols[13]);
    var sectorETF = cleanTicker(cols[14]);
    var sectorReturn = cleanPct(cols[15]);

    var ccy = detectCurrency(sellCcy, buyCcy);

    if (!costAmount || costAmount === 0) continue;

    var holdDays = 0;
    if (tradeDate && sellDate) {
      holdDays = daysBetween(tradeDate, sellDate);
    }

    var nominalReturn = (sellAmount && costAmount) ? (sellAmount / costAmount) - 1 : (pnlLocal ? pnlLocal / costAmount : 0);

    lots.push({
      ticker: ticker,
      ccy: ccy,
      tradeDate: tradeDate,
      sellDate: sellDate,
      costAmount: costAmount,
      sellAmount: sellAmount || (costAmount + (pnlLocal || 0)),
      pnlLocal: pnlLocal,
      pnlUSD: pnlUSD,
      marketBeta: marketBeta,
      indexName: indexName,
      indexShort: indexShort,
      indexReturn: indexReturn,
      sectorBeta: sectorBeta,
      sectorETF: sectorETF,
      sectorReturn: sectorReturn,
      holdDays: holdDays,
      nominalReturn: nominalReturn,
    });
  }
  return lots;
}

// ─── MFRA CALCULATIONS ──────────────────────────────────────
function computeMFRA(lots) {
  return lots.map(function(lot) {
    var mkt = null;
    var sec = null;
    var alpha = null;
    var excessSectorReturn = null;

    if (lot.marketBeta != null && lot.indexReturn != null) {
      mkt = lot.marketBeta * lot.indexReturn;
    }
    if (lot.sectorBeta != null && lot.sectorReturn != null && lot.indexReturn != null) {
      excessSectorReturn = lot.sectorReturn - lot.indexReturn;
      sec = lot.sectorBeta * excessSectorReturn;
    }
    if (mkt != null) {
      alpha = lot.nominalReturn - mkt - (sec || 0);
    }

    // USD conversion
    var approxFx = APPROX_FX[lot.ccy] || 1.0;
    var costUSD = lot.costAmount;
    var pnlUSDCalc = lot.pnlUSD;

    if (lot.ccy !== 'USD') {
      if (lot.pnlLocal != null && lot.pnlLocal !== 0 && lot.pnlUSD != null && lot.pnlUSD !== 0) {
        var impliedRatio = lot.pnlUSD / lot.pnlLocal;
        costUSD = lot.costAmount * impliedRatio;
      } else {
        costUSD = lot.costAmount * approxFx;
      }
      if (pnlUSDCalc == null) {
        pnlUSDCalc = (lot.pnlLocal || 0) * approxFx;
      }
    } else {
      if (pnlUSDCalc == null) pnlUSDCalc = lot.pnlLocal || 0;
    }

    var fxEffect = 0;
    if (lot.ccy !== 'USD' && lot.pnlUSD != null && lot.pnlLocal != null) {
      fxEffect = lot.pnlUSD - (lot.pnlLocal * approxFx);
    }

    var annualizedReturn = 0;
    if (lot.holdDays > 0) {
      annualizedReturn = Math.pow(1 + lot.nominalReturn, 365 / lot.holdDays) - 1;
    }

    return s(lot, {
      marketComponent: mkt,
      sectorComponent: sec,
      excessSectorReturn: excessSectorReturn,
      alpha: alpha,
      costUSD: costUSD,
      pnlUSDCalc: pnlUSDCalc,
      fxEffect: fxEffect,
      annualizedReturn: annualizedReturn,
      isNonUSD: lot.ccy !== 'USD',
    });
  });
}

function aggregatePositions(computedLots) {
  var map = {};
  computedLots.forEach(function(lot) {
    if (!map[lot.ticker]) {
      map[lot.ticker] = {
        ticker: lot.ticker,
        ccy: lot.ccy,
        lots: [],
        totalCostUSD: 0,
        totalPnlUSD: 0,
        totalCostLocal: 0,
        totalPnlLocal: 0,
        sectorETF: lot.sectorETF,
        indexShort: lot.indexShort,
        isNonUSD: lot.isNonUSD,
        fxEffect: 0,
      };
    }
    var pos = map[lot.ticker];
    pos.lots.push(lot);
    pos.totalCostUSD += lot.costUSD || 0;
    pos.totalPnlUSD += lot.pnlUSDCalc || 0;
    pos.totalCostLocal += lot.costAmount || 0;
    pos.totalPnlLocal += lot.pnlLocal || 0;
    pos.fxEffect += lot.fxEffect || 0;
  });

  var positions = Object.keys(map).map(function(ticker) {
    var pos = map[ticker];
    var lots = pos.lots;
    var totalCost = pos.totalCostUSD;

    // cost-weighted averages
    var wAlpha = 0, wMkt = 0, wSec = 0, wNom = 0, wAnn = 0, wIdx = 0;
    var validCost = 0;

    lots.forEach(function(lot) {
      var w = lot.costUSD || 0;
      wNom += lot.nominalReturn * w;
      wAnn += lot.annualizedReturn * w;
      if (lot.alpha != null) {
        wAlpha += lot.alpha * w;
        wMkt += (lot.marketComponent || 0) * w;
        wSec += (lot.sectorComponent || 0) * w;
        validCost += w;
      }
      if (lot.indexReturn != null) {
        wIdx += lot.indexReturn * w;
      }
    });

    var avgHold = lots.reduce(function(a, l) { return a + l.holdDays; }, 0) / lots.length;
    var nominalReturn = totalCost > 0 ? wNom / totalCost : 0;
    var annualizedReturn = totalCost > 0 ? wAnn / totalCost : 0;
    var indexReturn = totalCost > 0 ? wIdx / totalCost : null;

    return s(pos, {
      numLots: lots.length,
      avgHoldDays: avgHold,
      nominalReturn: nominalReturn,
      annualizedReturn: annualizedReturn,
      indexReturn: indexReturn,
      returnPct: totalCost > 0 ? pos.totalPnlUSD / totalCost : 0,
      alpha: validCost > 0 ? wAlpha / validCost : null,
      marketComponent: validCost > 0 ? wMkt / validCost : null,
      sectorComponent: validCost > 0 ? wSec / validCost : null,
      alphaDollar: validCost > 0 ? (wAlpha / validCost) * totalCost : 0,
    });
  });

  return positions;
}

function computePortfolioMetrics(positions, dividendIncome) {
  var totalCostUSD = 0;
  var totalPnlUSD = 0;
  var grossProfit = 0;
  var grossLoss = 0;
  var wins = 0, losses = 0, flat = 0;
  var nonUSDCost = 0;
  var nonUSDCount = 0;
  var totalFxEffect = 0;
  var wMkt = 0, wSec = 0, wAlpha = 0;
  var validCost = 0;
  var alphaWins = 0, alphaTotal = 0;

  positions.forEach(function(pos) {
    totalCostUSD += pos.totalCostUSD;
    totalPnlUSD += pos.totalPnlUSD;
    if (pos.totalPnlUSD > 0) { grossProfit += pos.totalPnlUSD; wins++; }
    else if (pos.totalPnlUSD < 0) { grossLoss += Math.abs(pos.totalPnlUSD); losses++; }
    else { flat++; }

    if (pos.isNonUSD) {
      nonUSDCost += pos.totalCostUSD;
      nonUSDCount++;
    }
    totalFxEffect += pos.fxEffect;

    if (pos.alpha != null) {
      wMkt += (pos.marketComponent || 0) * pos.totalCostUSD;
      wSec += (pos.sectorComponent || 0) * pos.totalCostUSD;
      wAlpha += (pos.alpha || 0) * pos.totalCostUSD;
      validCost += pos.totalCostUSD;
      alphaTotal++;
      if (pos.alpha > 0) alphaWins++;
    }
  });

  var div = dividendIncome || 0;
  var totalPnlInclDiv = totalPnlUSD + div;
  var totalReturn = totalCostUSD > 0 ? totalPnlUSD / totalCostUSD : 0;
  var totalReturnInclDiv = totalCostUSD > 0 ? totalPnlInclDiv / totalCostUSD : 0;
  var pfCapGains = grossLoss > 0 ? grossProfit / grossLoss : (grossProfit > 0 ? Infinity : 0);
  var pfInclDiv = grossLoss > 0 ? (grossProfit + div) / grossLoss : ((grossProfit + div) > 0 ? Infinity : 0);
  var fxPct = totalCostUSD > 0 ? nonUSDCost / totalCostUSD : 0;
  var portMkt = validCost > 0 ? wMkt / validCost : 0;
  var portSec = validCost > 0 ? wSec / validCost : 0;
  var portAlpha = validCost > 0 ? wAlpha / validCost : 0;
  var alphaHitRate = alphaTotal > 0 ? alphaWins / alphaTotal : 0;

  return {
    totalCostUSD: totalCostUSD,
    totalPnlUSD: totalPnlUSD,
    totalPnlInclDiv: totalPnlInclDiv,
    grossProfit: grossProfit,
    grossLoss: grossLoss,
    wins: wins,
    losses: losses,
    flat: flat,
    totalReturn: totalReturn,
    totalReturnInclDiv: totalReturnInclDiv,
    pfCapGains: pfCapGains,
    pfInclDiv: pfInclDiv,
    dividendIncome: div,
    fxPct: fxPct,
    nonUSDCount: nonUSDCount,
    totalFxEffect: totalFxEffect,
    portMkt: portMkt,
    portSec: portSec,
    portAlpha: portAlpha,
    alphaHitRate: alphaHitRate,
    validCost: validCost,
  };
}

// ─── FORMAT HELPERS ──────────────────────────────────────────
function fmt(n, decimals) {
  if (n == null) return '—';
  if (decimals === undefined) decimals = 0;
  var sign = n < 0 ? '-' : '';
  var abs = Math.abs(n);
  var parts = abs.toFixed(decimals).split('.');
  var intPart = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return sign + '$' + intPart + (parts[1] ? '.' + parts[1] : '');
}

function fmtPct(n, decimals) {
  if (n == null) return '—';
  if (decimals === undefined) decimals = 1;
  return (n * 100).toFixed(decimals) + '%';
}

function fmtNum(n, decimals) {
  if (n == null) return '—';
  if (decimals === undefined) decimals = 2;
  return n.toFixed(decimals);
}

function valColor(n) {
  if (n == null) return COLORS.muted;
  if (n > 0) return COLORS.green;
  if (n < 0) return COLORS.red;
  return COLORS.white;
}

// ─── MAIN COMPONENT ─────────────────────────────────────────
function MFRADashboard() {
  var _rawData = useState('');
  var rawData = _rawData[0];
  var setRawData = _rawData[1];

  var _clientName = useState('');
  var clientName = _clientName[0];
  var setClientName = _clientName[1];

  var _dividendInput = useState('');
  var dividendInput = _dividendInput[0];
  var setDividendInput = _dividendInput[1];

  var _tab = useState(0);
  var tab = _tab[0];
  var setTab = _tab[1];

  var _lots = useState([]);
  var lots = _lots[0];
  var setLots = _lots[1];

  var _sortConfig = useState({ key: null, dir: 'desc' });
  var sortConfig = _sortConfig[0];
  var setSortConfig = _sortConfig[1];

  var dividendIncome = parseFloat((dividendInput || '0').replace(/\s/g, '').replace(/,/g, '')) || 0;

  // ─── Computed data ───
  var computed = useMemo(function() {
    if (lots.length === 0) return null;
    var withMFRA = computeMFRA(lots);
    var positions = aggregatePositions(withMFRA);
    var metrics = computePortfolioMetrics(positions, dividendIncome);
    return { lots: withMFRA, positions: positions, metrics: metrics };
  }, [lots, dividendIncome]);

  var hasData = computed != null;

  // ─── Process button ───
  function handleProcess() {
    var parsed = parseData(rawData);
    if (parsed.length > 0) {
      setLots(parsed);
      setTab(1);
    }
  }

  // ─── Sort helper ───
  function sortBy(key) {
    setSortConfig(function(prev) {
      if (prev.key === key) {
        return { key: key, dir: prev.dir === 'asc' ? 'desc' : 'asc' };
      }
      return { key: key, dir: 'desc' };
    });
  }

  function sortedPositions(posArr) {
    if (!sortConfig.key) return posArr;
    var k = sortConfig.key;
    var dir = sortConfig.dir === 'asc' ? 1 : -1;
    return posArr.slice().sort(function(a, b) {
      var av = a[k]; var bv = b[k];
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') return av.localeCompare(bv) * dir;
      return (av - bv) * dir;
    });
  }

  function sortArrow(key) {
    if (sortConfig.key !== key) return '';
    return sortConfig.dir === 'asc' ? ' ▲' : ' ▼';
  }

  // ─── KPI Card ───
  function renderKPI(label, value, valueColor, subtitle) {
    return React.createElement('div', { style: cardStyle },
      React.createElement('div', { style: kpiLabelStyle }, label),
      React.createElement('div', { style: s(kpiValueStyle, { color: valueColor || COLORS.white }) }, value),
      subtitle ? React.createElement('div', { style: kpiSubStyle }, subtitle) : null
    );
  }

  // ─── Bar chart (div-based) ───
  function renderBarChart(items, maxAbs) {
    if (!maxAbs) {
      maxAbs = items.reduce(function(m, it) { return Math.max(m, Math.abs(it.value)); }, 1);
    }
    return React.createElement('div', { style: s(cardStyle, { marginTop: '16px' }) },
      items.map(function(item, idx) {
        var pct = Math.abs(item.value) / maxAbs * 100;
        var isPos = item.value >= 0;
        return React.createElement('div', {
          key: idx,
          style: { display: 'flex', alignItems: 'center', marginBottom: '4px', fontSize: '11px' }
        },
          React.createElement('div', {
            style: { width: '120px', textAlign: 'right', paddingRight: '8px', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
          }, item.label),
          React.createElement('div', { style: { flex: 1, position: 'relative', height: '18px' } },
            React.createElement('div', {
              style: {
                position: 'absolute',
                left: isPos ? '50%' : (50 - pct / 2) + '%',
                width: (pct / 2) + '%',
                height: '100%',
                backgroundColor: isPos ? COLORS.green : COLORS.red,
                borderRadius: '2px',
                opacity: 0.7,
              }
            })
          ),
          React.createElement('div', {
            style: { width: '100px', textAlign: 'right', paddingLeft: '8px', color: valColor(item.value), flexShrink: 0 }
          }, fmt(item.value, 0))
        );
      })
    );
  }

  // ─── Table helper ───
  function renderTable(columns, rows) {
    return React.createElement('div', { style: s(cardStyle, { marginTop: '16px', overflowX: 'auto', padding: '0' }) },
      React.createElement('table', {
        style: { width: '100%', borderCollapse: 'collapse', fontFamily: FONT, fontSize: '12px' }
      },
        React.createElement('thead', null,
          React.createElement('tr', null,
            columns.map(function(col, ci) {
              return React.createElement('th', {
                key: ci,
                style: s(tableHeaderStyle, { textAlign: col.align || 'left' }),
                onClick: function() { if (col.sortKey) sortBy(col.sortKey); }
              }, col.label + (col.sortKey ? sortArrow(col.sortKey) : ''));
            })
          )
        ),
        React.createElement('tbody', null,
          rows.map(function(row, ri) {
            return React.createElement('tr', {
              key: ri,
              style: { backgroundColor: ri % 2 === 0 ? 'transparent' : COLORS.rowAlt }
            },
              columns.map(function(col, ci) {
                var val = col.render ? col.render(row) : row[col.key];
                var color = col.colorFn ? col.colorFn(row) : COLORS.white;
                return React.createElement('td', {
                  key: ci,
                  style: s(tableCellStyle, { textAlign: col.align || 'left', color: color })
                }, val);
              })
            );
          })
        )
      )
    );
  }

  // ─── TAB: Data Input ───
  function renderDataInput() {
    return React.createElement('div', null,
      React.createElement('div', { style: { display: 'flex', gap: '16px', marginBottom: '16px' } },
        React.createElement('div', { style: { flex: 1 } },
          React.createElement('label', { style: s(kpiLabelStyle, { display: 'block', marginBottom: '8px' }) }, 'CLIENT NAME'),
          React.createElement('input', {
            type: 'text',
            value: clientName,
            onChange: function(e) { setClientName(e.target.value); },
            placeholder: 'Enter client name...',
            style: {
              width: '100%',
              padding: '10px 12px',
              fontFamily: FONT,
              fontSize: '13px',
              backgroundColor: COLORS.card,
              border: '1px solid ' + COLORS.border,
              borderRadius: '6px',
              color: COLORS.white,
              outline: 'none',
              boxSizing: 'border-box',
            }
          })
        ),
        React.createElement('div', { style: { width: '240px' } },
          React.createElement('label', { style: s(kpiLabelStyle, { display: 'block', marginBottom: '8px' }) }, 'TOTAL DIVIDEND INCOME (USD)'),
          React.createElement('input', {
            type: 'text',
            value: dividendInput,
            onChange: function(e) { setDividendInput(e.target.value); },
            placeholder: '0',
            style: {
              width: '100%',
              padding: '10px 12px',
              fontFamily: FONT,
              fontSize: '13px',
              backgroundColor: COLORS.card,
              border: '1px solid ' + COLORS.border,
              borderRadius: '6px',
              color: COLORS.white,
              outline: 'none',
              boxSizing: 'border-box',
            }
          })
        )
      ),
      React.createElement('label', { style: s(kpiLabelStyle, { display: 'block', marginBottom: '8px' }) }, 'PASTE PORTFOLIO DATA (TAB-SEPARATED)'),
      React.createElement('textarea', {
        value: rawData,
        onChange: function(e) { setRawData(e.target.value); },
        placeholder: 'Ticker\tCurrency\tTrade date\tSell date\tTotal purchase amount\tCurrency\tTotal sell amount\tPnL in local currency\tPnL in USD\tBeta vs relative index\trelative index\tRelative index (short)\tRelative index performance (%)\tsector beta\tsector ETF\trelative sector performance (%)\n\nPaste your data here...',
        rows: 16,
        style: {
          width: '100%',
          padding: '12px',
          fontFamily: FONT,
          fontSize: '11px',
          backgroundColor: COLORS.card,
          border: '1px solid ' + COLORS.border,
          borderRadius: '6px',
          color: COLORS.white,
          resize: 'vertical',
          outline: 'none',
          lineHeight: '1.5',
          boxSizing: 'border-box',
        }
      }),
      React.createElement('div', { style: { marginTop: '16px', display: 'flex', alignItems: 'center', gap: '16px' } },
        React.createElement('button', {
          onClick: handleProcess,
          style: {
            padding: '12px 32px',
            fontFamily: FONT,
            fontSize: '13px',
            fontWeight: '700',
            backgroundColor: COLORS.blue,
            color: '#000',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            letterSpacing: '0.5px',
          }
        }, 'PROCESS DATA'),
        lots.length > 0
          ? React.createElement('span', { style: { color: COLORS.green, fontSize: '12px' } }, '✓ ' + lots.length + ' lots loaded across ' + (computed ? computed.positions.length : 0) + ' positions')
          : null
      )
    );
  }

  // ─── Placeholder tabs (stages 2-7 will fill these) ───
  function renderOverview() {
    var m = computed.metrics;
    var positions = computed.positions;

    // Sector attribution
    var sectorMap = {};
    positions.forEach(function(pos) {
      var sec = pos.sectorETF || 'Unknown';
      if (!sectorMap[sec]) {
        sectorMap[sec] = { sector: sec, count: 0, totalCost: 0, totalPnl: 0, wAlpha: 0, validCost: 0 };
      }
      var sm = sectorMap[sec];
      sm.count++;
      sm.totalCost += pos.totalCostUSD;
      sm.totalPnl += pos.totalPnlUSD;
      if (pos.alpha != null) {
        sm.wAlpha += pos.alpha * pos.totalCostUSD;
        sm.validCost += pos.totalCostUSD;
      }
    });
    var sectors = Object.keys(sectorMap).map(function(k) {
      var sec = sectorMap[k];
      return s(sec, {
        weight: m.totalCostUSD > 0 ? sec.totalCost / m.totalCostUSD : 0,
        returnPct: sec.totalCost > 0 ? sec.totalPnl / sec.totalCost : 0,
        weightedAlpha: sec.validCost > 0 ? sec.wAlpha / sec.validCost : null,
      });
    }).sort(function(a, b) { return b.totalCost - a.totalCost; });

    // Top 5 / Bottom 5
    var byPnl = positions.slice().sort(function(a, b) { return b.totalPnlUSD - a.totalPnlUSD; });
    var top5 = byPnl.slice(0, 5);
    var bottom5 = byPnl.slice(-5).reverse();

    var gridRow = { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '12px' };

    return React.createElement('div', null,
      // Row 1: 4 KPIs
      React.createElement('div', { style: gridRow },
        renderKPI('CAPITAL DEPLOYED', fmt(m.totalCostUSD, 0), COLORS.white),
        renderKPI('TOTAL P&L', fmt(m.totalPnlInclDiv, 0), valColor(m.totalPnlInclDiv),
          'Cap gains: ' + fmt(m.totalPnlUSD, 0) + ' + Div: ' + fmt(m.dividendIncome, 0)),
        renderKPI('TOTAL RETURN', fmtPct(m.totalReturnInclDiv, 2), valColor(m.totalReturnInclDiv),
          'Cap: ' + fmtPct(m.totalReturn, 2) + ' + Div: ' + fmtPct(m.totalCostUSD > 0 ? m.dividendIncome / m.totalCostUSD : 0, 2)),
        renderKPI('WIN / LOSS / FLAT', m.wins + ' / ' + m.losses + ' / ' + m.flat, COLORS.white,
          'Win rate: ' + fmtPct(m.wins / (m.wins + m.losses + m.flat), 1))
      ),
      // Row 2: 4 KPIs
      React.createElement('div', { style: gridRow },
        renderKPI('PROFIT FACTOR', fmtNum(m.pfInclDiv, 2), m.pfInclDiv >= 1 ? COLORS.green : COLORS.red,
          'Cap gains only: ' + fmtNum(m.pfCapGains, 2)),
        renderKPI('FX EXPOSURE', fmtPct(m.fxPct, 1), m.fxPct > 0.3 ? COLORS.amber : COLORS.white,
          m.nonUSDCount + ' non-USD positions · FX effect: ' + fmt(m.totalFxEffect, 0)),
        renderKPI('IDIOSYNCRATIC ALPHA', fmtPct(m.portAlpha, 2), valColor(m.portAlpha),
          'Portfolio cost-weighted'),
        renderKPI('ALPHA HIT RATE', fmtPct(m.alphaHitRate, 1), m.alphaHitRate >= 0.5 ? COLORS.green : COLORS.red,
          'Positions with positive alpha')
      ),

      // MFRA Decomposition panel
      React.createElement('div', { style: s(cardStyle, { marginTop: '16px', marginBottom: '16px' }) },
        React.createElement('div', { style: s(kpiLabelStyle, { marginBottom: '12px' }) }, 'MFRA RETURN DECOMPOSITION (COST-WEIGHTED)'),
        React.createElement('div', { style: { display: 'flex', gap: '32px' } },
          React.createElement('div', null,
            React.createElement('span', { style: { color: COLORS.blue, fontSize: '20px', fontWeight: '700' } }, fmtPct(m.portMkt, 2)),
            React.createElement('span', { style: { color: COLORS.muted, fontSize: '11px', marginLeft: '8px' } }, 'Market \u03B2')
          ),
          React.createElement('div', { style: { color: COLORS.muted, fontSize: '20px' } }, '+'),
          React.createElement('div', null,
            React.createElement('span', { style: { color: COLORS.purple, fontSize: '20px', fontWeight: '700' } }, fmtPct(m.portSec, 2)),
            React.createElement('span', { style: { color: COLORS.muted, fontSize: '11px', marginLeft: '8px' } }, 'Excess Sector \u03B2')
          ),
          React.createElement('div', { style: { color: COLORS.muted, fontSize: '20px' } }, '+'),
          React.createElement('div', null,
            React.createElement('span', { style: { color: valColor(m.portAlpha), fontSize: '20px', fontWeight: '700' } }, fmtPct(m.portAlpha, 2)),
            React.createElement('span', { style: { color: COLORS.muted, fontSize: '11px', marginLeft: '8px' } }, 'Alpha (\u03B1)')
          ),
          React.createElement('div', { style: { color: COLORS.muted, fontSize: '20px' } }, '='),
          React.createElement('div', null,
            React.createElement('span', { style: { color: valColor(m.totalReturn), fontSize: '20px', fontWeight: '700' } }, fmtPct(m.totalReturn, 2)),
            React.createElement('span', { style: { color: COLORS.muted, fontSize: '11px', marginLeft: '8px' } }, 'Nominal')
          )
        )
      ),

      // Top 5 / Bottom 5
      React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' } },
        React.createElement('div', { style: cardStyle },
          React.createElement('div', { style: s(kpiLabelStyle, { marginBottom: '8px' }) }, 'TOP 5 BY P&L'),
          top5.map(function(p, i) {
            return React.createElement('div', {
              key: i,
              style: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: '12px' }
            },
              React.createElement('span', null, p.ticker),
              React.createElement('span', { style: { color: valColor(p.totalPnlUSD) } }, fmt(p.totalPnlUSD, 0) + ' (' + fmtPct(p.returnPct, 1) + ')')
            );
          })
        ),
        React.createElement('div', { style: cardStyle },
          React.createElement('div', { style: s(kpiLabelStyle, { marginBottom: '8px' }) }, 'BOTTOM 5 BY P&L'),
          bottom5.map(function(p, i) {
            return React.createElement('div', {
              key: i,
              style: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: '12px' }
            },
              React.createElement('span', null, p.ticker),
              React.createElement('span', { style: { color: valColor(p.totalPnlUSD) } }, fmt(p.totalPnlUSD, 0) + ' (' + fmtPct(p.returnPct, 1) + ')')
            );
          })
        )
      ),

      // Sector attribution table
      React.createElement('div', { style: s(kpiLabelStyle, { marginBottom: '8px' }) }, 'SECTOR ATTRIBUTION'),
      renderTable(
        [
          { label: 'Sector ETF', key: 'sector', sortKey: 'sector' },
          { label: '#', sortKey: 'count', align: 'right', render: function(r) { return r.count; } },
          { label: 'Weight', sortKey: 'weight', align: 'right', render: function(r) { return fmtPct(r.weight, 1); } },
          { label: 'P&L', sortKey: 'totalPnl', align: 'right', render: function(r) { return fmt(r.totalPnl, 0); }, colorFn: function(r) { return valColor(r.totalPnl); } },
          { label: 'Return', sortKey: 'returnPct', align: 'right', render: function(r) { return fmtPct(r.returnPct, 1); }, colorFn: function(r) { return valColor(r.returnPct); } },
          { label: 'W. Alpha', sortKey: 'weightedAlpha', align: 'right', render: function(r) { return fmtPct(r.weightedAlpha, 2); }, colorFn: function(r) { return valColor(r.weightedAlpha); } },
        ],
        sectors
      )
    );
  }

  function renderNominal() {
    var m = computed.metrics;
    var positions = computed.positions;
    var gridRow = { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '12px' };

    // Waterfall data
    var waterfallItems = positions.slice().sort(function(a, b) { return b.totalPnlUSD - a.totalPnlUSD; })
      .map(function(p) { return { label: p.ticker, value: p.totalPnlUSD }; });

    var nomCols = [
      { label: 'Ticker', key: 'ticker', sortKey: 'ticker' },
      { label: 'CCY', key: 'ccy', sortKey: 'ccy' },
      { label: '#Lots', sortKey: 'numLots', align: 'right', render: function(r) { return r.numLots; } },
      { label: 'Hold (d)', sortKey: 'avgHoldDays', align: 'right', render: function(r) { return Math.round(r.avgHoldDays); } },
      { label: 'Cost', sortKey: 'totalCostUSD', align: 'right', render: function(r) { return fmt(r.totalCostUSD, 0); } },
      { label: 'Exit', sortKey: 'totalPnlUSD', align: 'right', render: function(r) { return fmt(r.totalCostUSD + r.totalPnlUSD, 0); } },
      { label: 'P&L', sortKey: 'totalPnlUSD', align: 'right', render: function(r) { return fmt(r.totalPnlUSD, 0); }, colorFn: function(r) { return valColor(r.totalPnlUSD); } },
      { label: 'Return', sortKey: 'nominalReturn', align: 'right', render: function(r) { return fmtPct(r.nominalReturn, 1); }, colorFn: function(r) { return valColor(r.nominalReturn); } },
      { label: 'Ann.', sortKey: 'annualizedReturn', align: 'right', render: function(r) { return fmtPct(r.annualizedReturn, 1); }, colorFn: function(r) { return valColor(r.annualizedReturn); } },
      { label: 'Idx Ret', sortKey: 'indexReturn', align: 'right', render: function(r) { return fmtPct(r.indexReturn, 1); }, colorFn: function(r) { return valColor(r.indexReturn); } },
      { label: 'Excess', align: 'right', render: function(r) { var ex = r.indexReturn != null ? r.nominalReturn - r.indexReturn : null; return fmtPct(ex, 1); }, colorFn: function(r) { var ex = r.indexReturn != null ? r.nominalReturn - r.indexReturn : null; return valColor(ex); } },
    ];

    return React.createElement('div', null,
      // 6 KPI cards in 2 rows of 3
      React.createElement('div', { style: gridRow },
        renderKPI('GROSS PROFIT', fmt(m.grossProfit, 0), COLORS.green),
        renderKPI('DIVIDEND INCOME', fmt(m.dividendIncome, 0), COLORS.blue),
        renderKPI('GROSS LOSS', fmt(-m.grossLoss, 0), COLORS.red)
      ),
      React.createElement('div', { style: gridRow },
        renderKPI('NET P&L', fmt(m.totalPnlInclDiv, 0), valColor(m.totalPnlInclDiv),
          'Cap gains: ' + fmt(m.totalPnlUSD, 0)),
        renderKPI('PROFIT FACTOR', fmtNum(m.pfInclDiv, 2) + ' (incl. div)', m.pfInclDiv >= 1 ? COLORS.green : COLORS.red,
          'Cap gains only: ' + fmtNum(m.pfCapGains, 2)),
        renderKPI('FX IMPACT', fmt(m.totalFxEffect, 0), valColor(m.totalFxEffect),
          m.nonUSDCount + ' non-USD positions')
      ),

      // Full sortable table
      React.createElement('div', { style: s(kpiLabelStyle, { marginTop: '16px', marginBottom: '8px' }) }, 'POSITION DETAIL'),
      renderTable(nomCols, sortedPositions(positions)),

      // P&L waterfall
      React.createElement('div', { style: s(kpiLabelStyle, { marginTop: '24px', marginBottom: '4px' }) }, 'P&L WATERFALL'),
      renderBarChart(waterfallItems)
    );
  }

  function renderRiskAdjusted() {
    var m = computed.metrics;
    var positions = computed.positions;
    var gridRow = { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '16px' };

    var mfraCols = [
      { label: 'Ticker', key: 'ticker', sortKey: 'ticker' },
      { label: '#Lots', sortKey: 'numLots', align: 'right', render: function(r) { return r.numLots; } },
      { label: 'Hold (d)', sortKey: 'avgHoldDays', align: 'right', render: function(r) { return Math.round(r.avgHoldDays); } },
      { label: 'Cost', sortKey: 'totalCostUSD', align: 'right', render: function(r) { return fmt(r.totalCostUSD, 0); } },
      { label: 'P&L', sortKey: 'totalPnlUSD', align: 'right', render: function(r) { return fmt(r.totalPnlUSD, 0); }, colorFn: function(r) { return valColor(r.totalPnlUSD); } },
      { label: 'Return', sortKey: 'nominalReturn', align: 'right', render: function(r) { return fmtPct(r.nominalReturn, 1); }, colorFn: function(r) { return valColor(r.nominalReturn); } },
      { label: 'Mkt \u03B2', sortKey: 'marketComponent', align: 'right', render: function(r) { return fmtPct(r.marketComponent, 2); }, colorFn: function(r) { return COLORS.blue; } },
      { label: 'Sec \u03B2 (excess)', sortKey: 'sectorComponent', align: 'right', render: function(r) { return fmtPct(r.sectorComponent, 2); }, colorFn: function(r) { return COLORS.purple; } },
      { label: 'Alpha', sortKey: 'alpha', align: 'right', render: function(r) { return fmtPct(r.alpha, 2); }, colorFn: function(r) { return valColor(r.alpha); } },
    ];

    // Alpha dollar chart
    var alphaItems = positions
      .filter(function(p) { return p.alpha != null; })
      .map(function(p) { return { label: p.ticker, value: p.alphaDollar }; })
      .sort(function(a, b) { return b.value - a.value; });

    return React.createElement('div', null,
      React.createElement('div', { style: gridRow },
        renderKPI('MARKET \u03B2 CONTRIBUTION', fmtPct(m.portMkt, 2), COLORS.blue, 'Cost-weighted portfolio'),
        renderKPI('EXCESS SECTOR \u03B2', fmtPct(m.portSec, 2), COLORS.purple, 'Orthogonalized (sector - market)'),
        renderKPI('ALPHA (\u03B1)', fmtPct(m.portAlpha, 2), valColor(m.portAlpha), 'Idiosyncratic return'),
        renderKPI('ALPHA HIT RATE', fmtPct(m.alphaHitRate, 1), m.alphaHitRate >= 0.5 ? COLORS.green : COLORS.red, 'Positions with \u03B1 > 0')
      ),

      React.createElement('div', { style: s(kpiLabelStyle, { marginBottom: '8px' }) }, 'MFRA DECOMPOSITION BY POSITION'),
      renderTable(mfraCols, sortedPositions(positions)),

      React.createElement('div', { style: s(kpiLabelStyle, { marginTop: '24px', marginBottom: '4px' }) }, 'ALPHA DOLLAR CONTRIBUTION (\u03B1 \u00D7 COST)'),
      renderBarChart(alphaItems)
    );
  }

  function renderAlphaMap() {
    var positions = computed.positions;
    var withAlpha = positions.filter(function(p) { return p.alpha != null; });

    // Histogram buckets
    var buckets = [
      { label: '< -100%', min: -Infinity, max: -1 },
      { label: '-100% to -50%', min: -1, max: -0.5 },
      { label: '-50% to -25%', min: -0.5, max: -0.25 },
      { label: '-25% to -10%', min: -0.25, max: -0.1 },
      { label: '-10% to 0%', min: -0.1, max: 0 },
      { label: '0% to 10%', min: 0, max: 0.1 },
      { label: '10% to 25%', min: 0.1, max: 0.25 },
      { label: '> 25%', min: 0.25, max: Infinity },
    ];

    var bucketData = buckets.map(function(b) {
      var tickers = withAlpha.filter(function(p) { return p.alpha >= b.min && p.alpha < b.max; });
      return { label: b.label, count: tickers.length, tickers: tickers.map(function(p) { return p.ticker; }) };
    });
    var maxCount = bucketData.reduce(function(m, b) { return Math.max(m, b.count); }, 1);

    // Scatter data
    var scatterData = withAlpha.map(function(p) {
      return { ticker: p.ticker, holdDays: p.avgHoldDays, alpha: p.alpha, cost: p.totalCostUSD };
    });
    var maxHold = scatterData.reduce(function(m, d) { return Math.max(m, d.holdDays); }, 1);
    var maxAlphaAbs = scatterData.reduce(function(m, d) { return Math.max(m, Math.abs(d.alpha)); }, 0.01);
    var maxCost = scatterData.reduce(function(m, d) { return Math.max(m, d.cost); }, 1);

    return React.createElement('div', null,
      // Histogram
      React.createElement('div', { style: s(kpiLabelStyle, { marginBottom: '8px' }) }, 'ALPHA DISTRIBUTION'),
      React.createElement('div', { style: cardStyle },
        bucketData.map(function(b, i) {
          var barWidth = (b.count / maxCount) * 100;
          return React.createElement('div', {
            key: i,
            style: { display: 'flex', alignItems: 'center', marginBottom: '6px', fontSize: '11px' }
          },
            React.createElement('div', { style: { width: '120px', textAlign: 'right', paddingRight: '8px', flexShrink: 0, color: COLORS.muted } }, b.label),
            React.createElement('div', { style: { width: '40px', textAlign: 'center', fontWeight: '700', flexShrink: 0 } }, b.count),
            React.createElement('div', { style: { flex: 1, position: 'relative', height: '20px' } },
              React.createElement('div', {
                style: {
                  width: barWidth + '%',
                  height: '100%',
                  backgroundColor: i < 5 ? COLORS.red : COLORS.green,
                  borderRadius: '2px',
                  opacity: 0.6,
                }
              })
            ),
            React.createElement('div', {
              style: { flex: 2, paddingLeft: '8px', fontSize: '10px', color: COLORS.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
            }, b.tickers.join(', '))
          );
        })
      ),

      // Scatter plot (div-based)
      React.createElement('div', { style: s(kpiLabelStyle, { marginTop: '24px', marginBottom: '8px' }) }, 'ALPHA vs HOLDING PERIOD'),
      React.createElement('div', { style: s(cardStyle, { position: 'relative', height: '350px', overflow: 'hidden' }) },
        // Y-axis label
        React.createElement('div', { style: { position: 'absolute', left: '4px', top: '4px', fontSize: '9px', color: COLORS.muted } }, 'Alpha %'),
        // X-axis label
        React.createElement('div', { style: { position: 'absolute', right: '8px', bottom: '4px', fontSize: '9px', color: COLORS.muted } }, 'Hold Days'),
        // Zero line
        React.createElement('div', {
          style: {
            position: 'absolute',
            left: '60px',
            right: '20px',
            top: (50) + '%',
            height: '1px',
            backgroundColor: COLORS.border,
          }
        }),
        // Dots
        scatterData.map(function(d, i) {
          var xPct = 60 + ((d.holdDays / maxHold) * (100 - 80 / 100 * 100));
          var xPos = 60 + (d.holdDays / maxHold) * 500;
          var yPos = 175 - (d.alpha / maxAlphaAbs) * 150;
          var size = 8 + (d.cost / maxCost) * 20;
          return React.createElement('div', {
            key: i,
            title: d.ticker + ': ' + fmtPct(d.alpha, 1) + ', ' + Math.round(d.holdDays) + 'd, ' + fmt(d.cost, 0),
            style: {
              position: 'absolute',
              left: xPos + 'px',
              top: yPos + 'px',
              width: size + 'px',
              height: size + 'px',
              borderRadius: '50%',
              backgroundColor: d.alpha >= 0 ? COLORS.green : COLORS.red,
              opacity: 0.6,
              transform: 'translate(-50%, -50%)',
              cursor: 'default',
            }
          },
            React.createElement('div', {
              style: { position: 'absolute', top: -(14) + 'px', left: '50%', transform: 'translateX(-50%)', fontSize: '8px', color: COLORS.muted, whiteSpace: 'nowrap' }
            }, d.ticker)
          );
        })
      )
    );
  }

  function renderBehavioral() {
    var positions = computed.positions;

    // Disposition effect
    var winners = positions.filter(function(p) { return p.totalPnlUSD > 0; });
    var losers = positions.filter(function(p) { return p.totalPnlUSD < 0; });
    var avgHoldWin = winners.length > 0 ? winners.reduce(function(a, p) { return a + p.avgHoldDays; }, 0) / winners.length : 0;
    var avgHoldLoss = losers.length > 0 ? losers.reduce(function(a, p) { return a + p.avgHoldDays; }, 0) / losers.length : 0;

    // Deep losses (>= 30% loss)
    var deepLosses = positions.filter(function(p) { return p.nominalReturn <= -0.30; });
    var deepLossDollars = deepLosses.reduce(function(a, p) { return a + p.totalPnlUSD; }, 0);

    // Concentration
    var sorted = positions.slice().sort(function(a, b) { return b.totalCostUSD - a.totalCostUSD; });
    var largest = sorted[0];
    var totalCost = computed.metrics.totalCostUSD;
    var largestPct = largest && totalCost > 0 ? largest.totalCostUSD / totalCost : 0;

    // Multi-lot positions
    var multiLot = positions.filter(function(p) { return p.numLots > 1; });
    var multiLotData = multiLot.map(function(p) {
      var lots = p.lots;
      var costs = lots.map(function(l) { return l.costAmount; });
      var avgCostChange = costs.length > 1 ? costs[costs.length - 1] - costs[0] : 0;
      var pattern = 'LEVEL';
      if (avgCostChange > costs[0] * 0.1) pattern = 'ADD UP';
      else if (avgCostChange < -costs[0] * 0.1) pattern = 'AVG DOWN';
      return {
        ticker: p.ticker,
        numLots: p.numLots,
        pattern: pattern,
        avgHoldDays: Math.round(p.avgHoldDays),
        nominalReturn: p.nominalReturn,
        totalPnlUSD: p.totalPnlUSD,
        alpha: p.alpha,
      };
    });

    var gridRow = { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '16px' };

    var patternColor = function(p) {
      if (p === 'AVG DOWN') return COLORS.red;
      if (p === 'ADD UP') return COLORS.green;
      return COLORS.muted;
    };

    return React.createElement('div', null,
      React.createElement('div', { style: gridRow },
        renderKPI('DISPOSITION EFFECT',
          Math.round(avgHoldWin) + 'd vs ' + Math.round(avgHoldLoss) + 'd',
          avgHoldWin < avgHoldLoss ? COLORS.amber : COLORS.green,
          'Avg hold: winners vs losers' + (avgHoldWin < avgHoldLoss ? ' — cutting winners early' : '')
        ),
        renderKPI('DEEP LOSSES (\u226530%)',
          deepLosses.length + ' positions',
          deepLosses.length > 0 ? COLORS.red : COLORS.green,
          'Capital destroyed: ' + fmt(deepLossDollars, 0)
        ),
        renderKPI('CONCENTRATION RISK',
          largest ? largest.ticker : '—',
          largestPct > 0.15 ? COLORS.amber : COLORS.white,
          fmtPct(largestPct, 1) + ' of capital'
        )
      ),

      React.createElement('div', { style: s(kpiLabelStyle, { marginBottom: '8px' }) }, 'MULTI-LOT AVERAGING BEHAVIOR'),
      multiLotData.length > 0 ? renderTable(
        [
          { label: 'Ticker', key: 'ticker', sortKey: 'ticker' },
          { label: '#Lots', sortKey: 'numLots', align: 'right', render: function(r) { return r.numLots; } },
          { label: 'Pattern', key: 'pattern', render: function(r) { return r.pattern; }, colorFn: function(r) { return patternColor(r.pattern); } },
          { label: 'Hold (d)', sortKey: 'avgHoldDays', align: 'right', render: function(r) { return r.avgHoldDays; } },
          { label: 'Return', sortKey: 'nominalReturn', align: 'right', render: function(r) { return fmtPct(r.nominalReturn, 1); }, colorFn: function(r) { return valColor(r.nominalReturn); } },
          { label: 'P&L', sortKey: 'totalPnlUSD', align: 'right', render: function(r) { return fmt(r.totalPnlUSD, 0); }, colorFn: function(r) { return valColor(r.totalPnlUSD); } },
          { label: 'Alpha', sortKey: 'alpha', align: 'right', render: function(r) { return fmtPct(r.alpha, 2); }, colorFn: function(r) { return valColor(r.alpha); } },
        ],
        multiLotData
      ) : React.createElement('div', { style: s(cardStyle, { color: COLORS.muted }) }, 'No multi-lot positions found')
    );
  }

  function renderInsights() {
    var m = computed.metrics;
    var positions = computed.positions;

    var winners = positions.filter(function(p) { return p.totalPnlUSD > 0; });
    var losers = positions.filter(function(p) { return p.totalPnlUSD < 0; });
    var avgHoldWin = winners.length > 0 ? winners.reduce(function(a, p) { return a + p.avgHoldDays; }, 0) / winners.length : 0;
    var avgHoldLoss = losers.length > 0 ? losers.reduce(function(a, p) { return a + p.avgHoldDays; }, 0) / losers.length : 0;

    var deepLosses = positions.filter(function(p) { return p.nominalReturn <= -0.30; });
    var deepLossDollars = deepLosses.reduce(function(a, p) { return a + p.totalPnlUSD; }, 0);

    var multiLot = positions.filter(function(p) { return p.numLots > 1; });
    var avgDownLosers = multiLot.filter(function(p) { return p.totalPnlUSD < 0; });

    var nonUSD = positions.filter(function(p) { return p.isNonUSD; });
    var fxHelped = nonUSD.filter(function(p) { return p.fxEffect > 0; });
    var fxHurt = nonUSD.filter(function(p) { return p.fxEffect < 0; });

    var prematureProfitTakers = winners.filter(function(p) {
      return p.avgHoldDays < 90 && p.nominalReturn > 0 && p.nominalReturn < 0.1;
    });

    // Sector concentration
    var sectorMap = {};
    positions.forEach(function(p) {
      var sec = p.sectorETF || 'Unknown';
      if (!sectorMap[sec]) sectorMap[sec] = 0;
      sectorMap[sec] += p.totalCostUSD;
    });
    var topSector = Object.keys(sectorMap).sort(function(a, b) { return sectorMap[b] - sectorMap[a]; })[0];
    var topSectorPct = m.totalCostUSD > 0 ? sectorMap[topSector] / m.totalCostUSD : 0;

    function section(title, content) {
      return React.createElement('div', { style: s(cardStyle, { marginBottom: '16px' }) },
        React.createElement('div', { style: s(kpiLabelStyle, { marginBottom: '10px', fontSize: '11px', color: COLORS.blue }) }, title),
        React.createElement('div', { style: { fontSize: '12px', lineHeight: '1.7', color: COLORS.white } }, content)
      );
    }

    function p(text) {
      return React.createElement('p', { style: { margin: '0 0 8px 0' } }, text);
    }

    function ul(items) {
      return React.createElement('ul', { style: { margin: '4px 0 8px 0', paddingLeft: '20px' } },
        items.map(function(item, i) {
          return React.createElement('li', { key: i, style: { marginBottom: '4px' } }, item);
        })
      );
    }

    // Market/sector/alpha dollar contributions
    var mktDollars = m.portMkt * m.validCost;
    var secDollars = m.portSec * m.validCost;
    var alphaDollars = m.portAlpha * m.validCost;

    return React.createElement('div', null,
      section('EXECUTIVE SUMMARY', React.createElement('div', null,
        p('Portfolio deployed ' + fmt(m.totalCostUSD, 0) + ' across ' + positions.length + ' positions (' + computed.lots.length + ' lots). ' +
          'Total P&L of ' + fmt(m.totalPnlInclDiv, 0) + ' (' + fmtPct(m.totalReturnInclDiv, 2) + '), comprising ' +
          fmt(m.totalPnlUSD, 0) + ' capital gains and ' + fmt(m.dividendIncome, 0) + ' dividend income.'),
        p('Win/loss record: ' + m.wins + '/' + m.losses + '/' + m.flat + ' (win rate ' + fmtPct(m.wins / Math.max(1, m.wins + m.losses + m.flat), 1) + '). ' +
          'Profit factor ' + fmtNum(m.pfInclDiv, 2) + ' including dividends (' + fmtNum(m.pfCapGains, 2) + ' cap gains only).'),
        p('MFRA decomposition: Market \u03B2 contributed ' + fmtPct(m.portMkt, 2) + ', excess sector \u03B2 ' + fmtPct(m.portSec, 2) + ', ' +
          'and idiosyncratic alpha ' + fmtPct(m.portAlpha, 2) + '. Alpha hit rate: ' + fmtPct(m.alphaHitRate, 1) + '.')
      )),

      section('WHERE RETURNS CAME FROM', React.createElement('div', null,
        p('Return attribution by source (dollar-weighted):'),
        ul([
          'Market \u03B2: ' + fmt(mktDollars, 0) + ' (' + fmtPct(m.portMkt, 2) + ') — systematic market exposure',
          'Excess Sector \u03B2: ' + fmt(secDollars, 0) + ' (' + fmtPct(m.portSec, 2) + ') — sector tilts beyond market',
          'Alpha (\u03B1): ' + fmt(alphaDollars, 0) + ' (' + fmtPct(m.portAlpha, 2) + ') — stock-specific skill',
          'Dividends: ' + fmt(m.dividendIncome, 0) + ' — income component',
        ]),
        p(m.portAlpha > 0
          ? 'The portfolio generated positive alpha, indicating stock selection added value beyond market and sector exposures.'
          : 'The portfolio generated negative alpha, suggesting stock selection detracted from returns. Market and sector beta were the primary return drivers.')
      )),

      section('FX EXPOSURE ANALYSIS', React.createElement('div', null,
        p(fmtPct(m.fxPct, 1) + ' of capital (' + fmt(m.fxPct * m.totalCostUSD, 0) + ') was deployed in ' + m.nonUSDCount + ' non-USD positions.'),
        p('Net FX effect estimate: ' + fmt(m.totalFxEffect, 0)),
        fxHelped.length > 0 ? p('FX tailwind: ' + fxHelped.map(function(p) { return p.ticker + ' (' + fmt(p.fxEffect, 0) + ')'; }).join(', ')) : null,
        fxHurt.length > 0 ? p('FX headwind: ' + fxHurt.map(function(p) { return p.ticker + ' (' + fmt(p.fxEffect, 0) + ')'; }).join(', ')) : null
      )),

      section('DEEP LOSSES (\u226530% DRAWDOWN)', React.createElement('div', null,
        deepLosses.length > 0
          ? React.createElement('div', null,
              p(deepLosses.length + ' positions closed at \u226530% loss, destroying ' + fmt(deepLossDollars, 0) + ' in capital:'),
              ul(deepLosses.map(function(pos) {
                return pos.ticker + ': ' + fmtPct(pos.nominalReturn, 1) + ' return, ' + fmt(pos.totalPnlUSD, 0) + ' P&L, ' +
                  Math.round(pos.avgHoldDays) + ' days held, alpha ' + fmtPct(pos.alpha, 2);
              }))
            )
          : p('No positions closed at \u226530% loss.')
      )),

      section('BEHAVIORAL PATTERNS', React.createElement('div', null,
        p('Disposition Effect: Winners held ' + Math.round(avgHoldWin) + ' days on average vs losers ' + Math.round(avgHoldLoss) + ' days. ' +
          (avgHoldWin < avgHoldLoss
            ? 'This is consistent with disposition bias — cutting winners early while holding losers too long.'
            : 'No strong disposition bias detected.')),
        avgDownLosers.length > 0
          ? React.createElement('div', null,
              p('Averaging down on losers: ' + avgDownLosers.length + ' multi-lot positions ended in losses:'),
              ul(avgDownLosers.map(function(pos) { return pos.ticker + ': ' + fmtPct(pos.nominalReturn, 1) + ', ' + fmt(pos.totalPnlUSD, 0); }))
            )
          : null,
        prematureProfitTakers.length > 0
          ? React.createElement('div', null,
              p('Premature profit-taking (sold <90 days with <10% gain): ' + prematureProfitTakers.length + ' positions:'),
              ul(prematureProfitTakers.map(function(pos) { return pos.ticker + ': ' + fmtPct(pos.nominalReturn, 1) + ' in ' + Math.round(pos.avgHoldDays) + ' days'; }))
            )
          : null
      )),

      section('RECOMMENDATIONS', React.createElement('div', null,
        ul([
          'Stop-loss discipline: Implement -20% hard stop-loss. ' + deepLosses.length + ' positions breached -30%, destroying ' + fmt(deepLossDollars, 0) + '. A -20% stop would have limited damage significantly.',
          'Averaging-down ban: Prohibit adding to losing positions without explicit thesis revalidation. Multi-lot losers amplified capital destruction.',
          (topSector ? 'Sector concentration: ' + topSector + ' represents ' + fmtPct(topSectorPct, 1) + ' of capital. Consider diversifying across sectors to reduce concentration risk.' : 'Maintain sector diversification.'),
          'Thesis expiry: Set 6-month review triggers for all positions. Positions held >400 days without positive alpha should be reassessed.',
          'Asymmetric exits: Let winners run beyond +10%. Current pattern of quick profit-taking leaves upside on the table. Consider trailing stops instead of fixed targets.',
          'FX hedging: With ' + fmtPct(m.fxPct, 1) + ' non-USD exposure and ' + fmt(m.totalFxEffect, 0) + ' net FX effect, consider hedging FX risk on positions >$50K or >6 month expected hold.',
          'Quarterly review: Schedule formal MFRA review each quarter to track alpha generation trends and behavioral pattern improvement.',
        ])
      ))
    );
  }

  // ─── MAIN RENDER ───
  return React.createElement('div', { style: baseStyle },
    // Header
    React.createElement('div', {
      style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }
    },
      React.createElement('div', null,
        React.createElement('h1', {
          style: { margin: 0, fontSize: '20px', fontWeight: '700', letterSpacing: '1px' }
        }, 'MFRA PORTFOLIO DASHBOARD'),
        clientName
          ? React.createElement('div', { style: { fontSize: '13px', color: COLORS.muted, marginTop: '4px' } }, clientName)
          : null
      ),
      hasData
        ? React.createElement('div', {
            style: { fontSize: '11px', color: COLORS.muted, textAlign: 'right' }
          },
            computed.positions.length + ' positions · ' + computed.lots.length + ' lots',
            React.createElement('br'),
            'Capital: ' + fmt(computed.metrics.totalCostUSD, 0)
          )
        : null
    ),

    // Tab bar
    React.createElement('div', {
      style: {
        display: 'flex',
        gap: '4px',
        marginBottom: '24px',
        borderBottom: '1px solid ' + COLORS.border,
        paddingBottom: '0',
        overflowX: 'auto',
      }
    },
      TAB_NAMES.map(function(name, idx) {
        var isActive = tab === idx;
        var isDisabled = idx > 0 && !hasData;
        return React.createElement('button', {
          key: idx,
          onClick: function() { if (!isDisabled) setTab(idx); },
          style: {
            padding: '10px 16px',
            fontFamily: FONT,
            fontSize: '11px',
            fontWeight: isActive ? '700' : '400',
            color: isDisabled ? COLORS.border : (isActive ? COLORS.blue : COLORS.muted),
            backgroundColor: 'transparent',
            border: 'none',
            borderBottom: isActive ? '2px solid ' + COLORS.blue : '2px solid transparent',
            cursor: isDisabled ? 'default' : 'pointer',
            letterSpacing: '0.5px',
            whiteSpace: 'nowrap',
            opacity: isDisabled ? 0.4 : 1,
          }
        }, name);
      })
    ),

    // Tab content
    tab === 0 ? renderDataInput() : null,
    tab === 1 && hasData ? renderOverview() : null,
    tab === 2 && hasData ? renderNominal() : null,
    tab === 3 && hasData ? renderRiskAdjusted() : null,
    tab === 4 && hasData ? renderAlphaMap() : null,
    tab === 5 && hasData ? renderBehavioral() : null,
    tab === 6 && hasData ? renderInsights() : null
  );
}

export default MFRADashboard;
