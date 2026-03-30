/**
 * API client for the backend.
 */
const API_BASE = import.meta.env.VITE_API_URL || '';

async function fetchJSON(url, options = {}) {
  const resp = await fetch(`${API_BASE}${url}`, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`API error ${resp.status}: ${text}`);
  }
  return resp.json();
}

export async function refreshData(fredApiKey) {
  const params = fredApiKey ? `?fred_api_key=${encodeURIComponent(fredApiKey)}` : '';
  return fetchJSON(`/api/refresh${params}`, { method: 'POST' });
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

export async function getFairValue(model = 'cpi', measure = 'headline') {
  const params = new URLSearchParams({ model, measure });
  return fetchJSON(`/api/fair-value?${params}`);
}

export async function getStir() {
  return fetchJSON('/api/stir');
}

export async function getSynthesis({ lookback = 21, volWindow = 21, volScaled = true } = {}) {
  const params = new URLSearchParams({
    lookback: lookback.toString(),
    vol_window: volWindow.toString(),
    vol_scaled: volScaled.toString(),
  });
  return fetchJSON(`/api/synthesis?${params}`);
}
