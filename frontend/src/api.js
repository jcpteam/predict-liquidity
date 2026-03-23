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

export function createOrderBookSocket(unifiedId, { onSnapshot, onBookUpdate, onPriceChange, onTrade, onKalshiUpdate, onBetfairUpdate, onBtxUpdate, onError, onOpen, onClose }) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/orderbooks/${unifiedId}`)

  ws.onopen = () => {
    if (onOpen) onOpen()
    // keep-alive ping every 30s
    ws._pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping')
    }, 30000)
  }

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data)
    switch (data.type) {
      case 'snapshot': if (onSnapshot) onSnapshot(data); break
      case 'book_update': if (onBookUpdate) onBookUpdate(data); break
      case 'price_change': if (onPriceChange) onPriceChange(data); break
      case 'trade': if (onTrade) onTrade(data); break
      case 'kalshi_update': if (onKalshiUpdate) onKalshiUpdate(data); break
      case 'betfair_update': if (onBetfairUpdate) onBetfairUpdate(data); break
      case 'btx_update': if (onBtxUpdate) onBtxUpdate(data); break
      case 'error': if (onError) onError(data.message); break
      case 'pong': break
      default: console.log('[ws] unknown message type:', data.type)
    }
  }

  ws.onerror = (e) => {
    console.error('WS error', e)
    if (onError) onError('WebSocket connection error')
  }

  ws.onclose = () => {
    if (ws._pingInterval) clearInterval(ws._pingInterval)
    if (onClose) onClose()
  }

  return ws
}
