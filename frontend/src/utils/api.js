/**
 * API client for the backend.
 * Includes retry logic with exponential backoff for resilience.
 */
const API_BASE = import.meta.env.VITE_API_URL || '';

// Simple in-memory cache
const _cache = {};
const CACHE_TTL = 30000; // 30 seconds

async function fetchJSON(url, options = {}) {
  const cacheKey = `${options.method || 'GET'}:${url}`;

  // Check cache for GET requests
  if (!options.method || options.method === 'GET') {
    const cached = _cache[cacheKey];
    if (cached && Date.now() - cached.time < CACHE_TTL) {
      return cached.data;
    }
  }

  // Retry with exponential backoff
  const maxRetries = 2;
  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const resp = await fetch(`${API_BASE}${url}`, options);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`API error ${resp.status}: ${text}`);
      }
      const data = await resp.json();

      // If backend says no data cached, treat as error so panels show clean message
      if (data && data.cached === false) {
        throw new Error(data.message || 'No data cached. Click Refresh to load.');
      }

      // Cache GET responses
      if (!options.method || options.method === 'GET') {
        _cache[cacheKey] = { data, time: Date.now() };
      }

      return data;
    } catch (e) {
      lastError = e;
      if (attempt < maxRetries) {
        await new Promise(r => setTimeout(r, 1000 * (attempt + 1))); // 1s, 2s backoff
      }
    }
  }
  throw lastError;
}

/** Clear all cached API responses */
export function clearCache() {
  Object.keys(_cache).forEach(k => delete _cache[k]);
}

export async function refreshData(fredApiKey) {
  const params = fredApiKey ? `?fred_api_key=${encodeURIComponent(fredApiKey)}` : '';
  return fetchJSON(`/api/refresh${params}`, { method: 'POST' });
}

export async function uploadBonds(file) {
  const formData = new FormData();
  formData.append('file', file);
  const resp = await fetch(`${API_BASE}/api/portfolio/upload-bonds`, { method: 'POST', body: formData });
  if (!resp.ok) { const t = await resp.text(); throw new Error(`Upload error ${resp.status}: ${t}`); }
  return resp.json();
}

export async function getBonds(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v !== '' && v != null) params.set(k, v.toString()); });
  return fetchJSON(`/api/portfolio/bonds?${params}`);
}

export async function optimizePortfolio(constraints = {}) {
  return fetchJSON('/api/portfolio/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(constraints),
  });
}

export async function getEquity(ticker) {
  return fetchJSON(`/api/portfolio/equity/${encodeURIComponent(ticker)}`);
}

export async function getTicHoldings({ rangeYears = 10, countries = '' } = {}) {
  const params = new URLSearchParams({ range_years: rangeYears.toString() });
  if (countries) params.set('countries', countries);
  return fetchJSON(`/api/tic-holdings?${params}`);
}

export async function getRegimes({ lookback = 21, volWindow = 21, volScaled = true, rangeDays = 500 } = {}) {
  const params = new URLSearchParams({
    lookback: lookback.toString(),
    vol_window: volWindow.toString(),
    vol_scaled: volScaled.toString(),
    range_days: rangeDays.toString(),
  });
  return fetchJSON(`/api/regimes?${params}`);
}

export async function getFredData(series) {
  const params = series ? `?series=${encodeURIComponent(series)}` : '';
  return fetchJSON(`/api/data/fred${params}`);
}

export async function getYahooData(tickers) {
  const params = tickers ? `?tickers=${encodeURIComponent(tickers)}` : '';
  return fetchJSON(`/api/data/yahoo${params}`);
}

export async function getMonthlyDerived(series) {
  const params = series ? `?series=${encodeURIComponent(series)}` : '';
  return fetchJSON(`/api/data/monthly${params}`);
}

export async function getStatus() {
  return fetchJSON('/api/status');
}

export async function getHealth() {
  return fetchJSON('/api/health');
}

export async function getRegimeDefinitions() {
  return fetchJSON('/api/regime-definitions');
}

export async function getRiskPremia({ rangeDays = 2520 } = {}) {
  const params = new URLSearchParams({ range_days: rangeDays.toString() });
  return fetchJSON(`/api/risk-premia?${params}`);
}

export async function getCurveRegimes({ pair = '10Y-2Y', lookback = 21, rangeDays = 504 } = {}) {
  const params = new URLSearchParams({ pair, lookback: lookback.toString(), range_days: rangeDays.toString() });
  return fetchJSON(`/api/curve-regimes?${params}`);
}

export async function getSectorFactors(sector = 'Energy', lookback = 10) {
  const params = new URLSearchParams({ sector, lookback: lookback.toString() });
  return fetchJSON(`/api/sectors/factors?${params}`);
}

export async function getStockLookup(ticker, lookback = 10, benchmark = 'SPY') {
  const params = new URLSearchParams({ ticker, lookback: lookback.toString(), benchmark });
  return fetchJSON(`/api/stock/lookup?${params}`);
}

export async function getFairValue(model = 'cpi', measure = 'headline') {
  const params = new URLSearchParams({ model, measure });
  return fetchJSON(`/api/fair-value?${params}`);
}

export async function getStir() {
  return fetchJSON('/api/stir');
}

// --- GLI (Global Liquidity Index) ---

export async function getGliFedNet() {
  return fetchJSON('/api/gli/fed-net-liquidity');
}

export async function getGliCentralBanks() {
  return fetchJSON('/api/gli/central-banks');
}

export async function getGliBisCredit() {
  return fetchJSON('/api/gli/bis-credit');
}

export async function getProductionSignal(model = '3fa_eq') {
  return fetchJSON(`/api/gli/production-signal?model=${model}`);
}

export async function optimizeCurrencyWeights() {
  return fetchJSON('/api/gli/optimize-currency-weights');
}

export async function runSignalValidation(model = '4f') {
  return fetchJSON(`/api/gli/run-validation?model=${model}`, { method: 'POST' });
}

export async function getSignalValidation() {
  return fetchJSON('/api/gli/signal-validation');
}

export async function runRegimeAnalysis() {
  return fetchJSON('/api/gli/run-regime-analysis', { method: 'POST' });
}

export async function getRegimeAnalysis() {
  return fetchJSON('/api/gli/regime-analysis');
}

export async function runImprovements(track = 'all') {
  return fetchJSON(`/api/gli/run-improvements?track=${track}`, { method: 'POST' });
}

export async function getImprovements() {
  return fetchJSON('/api/gli/improvements');
}

export async function getComponentDetail() {
  return fetchJSON('/api/gli/component-detail');
}

export async function getBacktestSweep(model = '3fa') {
  return fetchJSON(`/api/gli/composite-backtest?mode=sweep&model=${model}`);
}

export async function getBacktestDetail(signalType, regimeFilter, model = '3fa') {
  const params = new URLSearchParams({ mode: 'detail', signal_type: signalType, regime_filter: regimeFilter, model });
  return fetchJSON(`/api/gli/composite-backtest?${params}`);
}

export async function getTickerOverlay(ticker, startDate = '2005-01-01') {
  return fetchJSON(`/api/ticker-overlay?ticker=${encodeURIComponent(ticker)}&start=${startDate}`);
}

export async function refreshGli(layer = 'fed') {
  return fetchJSON(`/api/gli/refresh?layer=${layer}`, { method: 'POST' });
}

export async function getSynthesis({ lookback = 21, volWindow = 21, volScaled = true } = {}) {
  const params = new URLSearchParams({
    lookback: lookback.toString(),
    vol_window: volWindow.toString(),
    vol_scaled: volScaled.toString(),
  });
  return fetchJSON(`/api/synthesis?${params}`);
}
