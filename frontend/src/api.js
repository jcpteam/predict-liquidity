const BASE = '/api'

export async function fetchLeagues() {
  const res = await fetch(`${BASE}/leagues`)
  return res.json()
}

export async function fetchLeagueEvents(league) {
  const res = await fetch(`${BASE}/leagues/${encodeURIComponent(league)}/events`)
  return res.json()
}

export async function syncEvents() {
  const res = await fetch(`${BASE}/events/sync`, { method: 'POST' })
  return res.json()
}

export async function fetchEventMapping(unifiedId) {
  const res = await fetch(`${BASE}/events/${unifiedId}/mapping`)
  return res.json()
}

export async function addMarketMapping(unifiedId, marketName, marketEventId) {
  const params = new URLSearchParams({ market_name: marketName, market_event_id: marketEventId })
  const res = await fetch(`${BASE}/events/${unifiedId}/mapping?${params}`, { method: 'PUT' })
  return res.json()
}

export async function removeMarketMapping(unifiedId, marketName) {
  await fetch(`${BASE}/events/${unifiedId}/mapping/${marketName}`, { method: 'DELETE' })
}

export async function fetchMarkets() {
  const res = await fetch(`${BASE}/markets`)
  return res.json()
}

export async function searchMarketEvents(marketName, query) {
  const params = new URLSearchParams({ q: query || '' })
  const res = await fetch(`${BASE}/markets/${marketName}/search?${params}`)
  return res.json()
}

export async function fetchOrderBooks(unifiedId) {
  const res = await fetch(`${BASE}/events/${unifiedId}/orderbooks`)
  return res.json()
}

export async function autoMatchMarket(marketName) {
  const res = await fetch(`${BASE}/automatch/${marketName}`, { method: 'POST' })
  return res.json()
}

export async function autoMatchAll() {
  const res = await fetch(`${BASE}/automatch`, { method: 'POST' })
  return res.json()
}

export function createLiveSocket(unifiedId, onMessage) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/live/${unifiedId}`)
  ws.onmessage = (e) => onMessage(JSON.parse(e.data))
  ws.onerror = (e) => console.error('WS error', e)
  return ws
}
