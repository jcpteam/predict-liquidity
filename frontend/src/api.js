const BASE = '/api'

export async function fetchMappings() {
  const res = await fetch(`${BASE}/mappings`)
  return res.json()
}

export async function createMapping(displayName, eventTime) {
  const params = new URLSearchParams({ display_name: displayName })
  if (eventTime) params.set('event_time', eventTime)
  const res = await fetch(`${BASE}/mappings?${params}`, { method: 'POST' })
  return res.json()
}

export async function deleteMapping(unifiedId) {
  await fetch(`${BASE}/mappings/${unifiedId}`, { method: 'DELETE' })
}

export async function addMarketToMapping(unifiedId, marketName, marketEventId) {
  const params = new URLSearchParams({ market_name: marketName, market_event_id: marketEventId })
  const res = await fetch(`${BASE}/mappings/${unifiedId}/market?${params}`, { method: 'PUT' })
  return res.json()
}

export async function removeMarketFromMapping(unifiedId, marketName) {
  await fetch(`${BASE}/mappings/${unifiedId}/market/${marketName}`, { method: 'DELETE' })
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

export async function fetchComparison(unifiedId) {
  const res = await fetch(`${BASE}/compare/${unifiedId}`)
  return res.json()
}

export function createLiveSocket(unifiedId, onMessage) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/live/${unifiedId}`)
  ws.onmessage = (e) => onMessage(JSON.parse(e.data))
  ws.onerror = (e) => console.error('WS error', e)
  return ws
}
