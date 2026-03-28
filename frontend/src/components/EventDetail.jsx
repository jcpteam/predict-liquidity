import React, { useState, useEffect, useRef, useCallback } from 'react'
import { fetchEventMapping, addMarketMapping, removeMarketMapping, searchMarketEvents, autoMatchMarket, createOrderBookSocket } from '../api'
import OrderBookChart from './OrderBookChart.jsx'

const MARKET_ORDER = ['btx', 'polymarket', 'kalshi', 'betfair']

// Normalize outcome names to canonical: Home / Away / Draw
const DRAW_NAMES = new Set(['draw', 'the draw', 'tie', 'x', 'DRAW'])
function normalizeOutcome(name) {
  if (!name) return name
  if (DRAW_NAMES.has(name.toLowerCase())) return 'Draw'
  return name
}

// Group outcomes across markets into columns
function buildOutcomeColumns(marketsData) {
  // Collect all outcomes per market
  const marketOutcomes = {} // {marketName: [{outcome, ...ev}]}
  for (const mname of MARKET_ORDER) {
    const events = marketsData[mname]
    if (!events || !Array.isArray(events) || events.length === 0) {
      marketOutcomes[mname] = []
      continue
    }
    marketOutcomes[mname] = events.map(ev => ({
      ...ev,
      _normalized: normalizeOutcome(ev.outcome),
    }))
  }

  // Find all unique normalized outcomes (use first market with data as reference)
  const outcomeOrder = []
  const seen = new Set()
  for (const mname of MARKET_ORDER) {
    for (const ev of marketOutcomes[mname]) {
      if (!seen.has(ev._normalized)) {
        seen.add(ev._normalized)
        outcomeOrder.push(ev._normalized)
      }
    }
  }

  // Build columns: [{normalizedOutcome, markets: {btx: ev, polymarket: ev, ...}}]
  return outcomeOrder.map(norm => {
    const col = { outcome: norm, markets: {} }
    for (const mname of MARKET_ORDER) {
      const match = marketOutcomes[mname].find(ev => ev._normalized === norm)
      col.markets[mname] = match || null
    }
    return col
  })
}

// Get best bid price for an outcome event
function getBestBid(ev) {
  if (!ev || !ev.order_book || !ev.order_book.bids || !ev.order_book.bids.length) return null
  return ev.order_book.bids[0].price
}
function getBestAsk(ev) {
  if (!ev || !ev.order_book || !ev.order_book.asks || !ev.order_book.asks.length) return null
  return ev.order_book.asks[0].price
}

export default function EventDetail({ unifiedId, markets, onMappingChange }) {
  const [mapping, setMapping] = useState(null)
  const [orderBookData, setOrderBookData] = useState(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [autoMatching, setAutoMatching] = useState(false)
  const [addingMarket, setAddingMarket] = useState(false)
  const [selectedMarket, setSelectedMarket] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [manualId, setManualId] = useState('')
  const matchAttemptedRef = useRef(false)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)

  const closeWs = useCallback(() => {
    if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = null }
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null }
    setWsConnected(false)
  }, [])

  const connectWs = useCallback((uid) => {
    closeWs()
    const ws = createOrderBookSocket(uid, {
      onSnapshot: (data) => {
        setOrderBookData({ unified_id: data.unified_id, display_name: data.display_name, markets: data.markets })
        setLastUpdate(new Date())
      },
      onBookUpdate: (data) => {
        setOrderBookData(prev => {
          if (!prev) return prev
          const pmEvents = [...(prev.markets.polymarket || [])]
          for (let i = 0; i < pmEvents.length; i++) {
            if (pmEvents[i].outcome === data.outcome || pmEvents[i].event_title === data.title) {
              pmEvents[i] = { ...pmEvents[i], order_book: { bids: data.bids, asks: data.asks } }
              break
            }
          }
          return { ...prev, markets: { ...prev.markets, polymarket: pmEvents } }
        })
        setLastUpdate(new Date())
      },
      onPriceChange: (data) => {
        setOrderBookData(prev => {
          if (!prev) return prev
          const pmEvents = [...(prev.markets.polymarket || [])]
          for (let i = 0; i < pmEvents.length; i++) {
            if (pmEvents[i].outcome === data.outcome) {
              pmEvents[i] = { ...pmEvents[i], last_price: parseFloat(data.price) || pmEvents[i].last_price }
              break
            }
          }
          return { ...prev, markets: { ...prev.markets, polymarket: pmEvents } }
        })
        setLastUpdate(new Date())
      },
      onTrade: () => setLastUpdate(new Date()),
      onKalshiUpdate: (data) => {
        setOrderBookData(prev => prev ? { ...prev, markets: { ...prev.markets, kalshi: data.events } } : prev)
        setLastUpdate(new Date())
      },
      onBetfairUpdate: (data) => {
        setOrderBookData(prev => prev ? { ...prev, markets: { ...prev.markets, betfair: data.events } } : prev)
        setLastUpdate(new Date())
      },
      onBtxUpdate: (data) => {
        setOrderBookData(prev => prev ? { ...prev, markets: { ...prev.markets, btx: data.events } } : prev)
        setLastUpdate(new Date())
      },
      onOpen: () => setWsConnected(true),
      onClose: () => {
        setWsConnected(false)
        reconnectTimer.current = setTimeout(() => connectWs(uid), 3000)
      },
      onError: (msg) => console.error('[ws]', msg),
    })
    wsRef.current = ws
  }, [closeWs])

  useEffect(() => {
    setOrderBookData(null)
    matchAttemptedRef.current = false
    closeWs()
    fetchEventMapping(unifiedId).then(setMapping)
    return () => closeWs()
  }, [unifiedId, closeWs])

  useEffect(() => {
    if (!mapping) return
    const otherMarkets = markets.filter(m => m !== 'btx')
    const unlinked = otherMarkets.filter(m => !mapping.mappings[m])
    const doAutoMatchAndConnect = async () => {
      if (unlinked.length > 0 && !matchAttemptedRef.current) {
        matchAttemptedRef.current = true
        setAutoMatching(true)
        try {
          for (const m of unlinked) await autoMatchMarket(m)
          const updated = await fetchEventMapping(unifiedId)
          setMapping(updated)
          onMappingChange()
        } catch (e) { console.error('Auto-match failed:', e) }
        finally { setAutoMatching(false) }
      }
      connectWs(unifiedId)
    }
    doAutoMatchAndConnect()
  }, [mapping?.unified_id])

  const otherMarkets = markets.filter(m => m !== 'btx')
  useEffect(() => {
    if (otherMarkets.length > 0 && !selectedMarket) setSelectedMarket(otherMarkets[0])
  }, [markets])

  const handleSearch = async () => {
    if (!selectedMarket) return
    setSearchResults(await searchMarketEvents(selectedMarket, searchQuery))
  }
  const handleAddMapping = async (marketEventId) => {
    await addMarketMapping(unifiedId, selectedMarket, marketEventId)
    setSearchResults([]); setManualId(''); setAddingMarket(false)
    const updated = await fetchEventMapping(unifiedId)
    setMapping(updated)
    onMappingChange()
    connectWs(unifiedId)
  }
  const handleRemove = async (marketName) => {
    await removeMarketMapping(unifiedId, marketName)
    const updated = await fetchEventMapping(unifiedId)
    setMapping(updated)
    onMappingChange()
  }

  if (!mapping) return <div className="detail-page"><p>Loading...</p></div>

  const columns = orderBookData ? buildOutcomeColumns(orderBookData.markets || {}) : []

  return (
    <div className="detail-page">
      <div className="detail-title-bar">
        <h2>{mapping.display_name}</h2>
        <div className="detail-title-meta">
          {mapping.event_time && <span className="detail-time">🕐 {new Date(mapping.event_time).toLocaleString()}</span>}
          {wsConnected ? <span className="live-dot">● LIVE</span> : <span className="auto-match-status">○ Connecting...</span>}
          {lastUpdate && <span className="timestamp">Updated: {lastUpdate.toLocaleTimeString()}</span>}
          {autoMatching && <span className="auto-match-status">🔄 Auto-matching...</span>}
        </div>
      </div>

      {/* Linked markets */}
      <div className="linked-section">
        <h3>Linked Markets</h3>
        <div className="linked-list">
          {Object.entries(mapping.mappings).map(([name, id]) => (
            <div key={name} className="linked-item">
              <span className="market-badge">{name}</span>
              <code>{id}</code>
              {name !== 'btx' && <button className="btn-danger btn-sm" onClick={() => handleRemove(name)}>✕</button>}
            </div>
          ))}
        </div>
        {!addingMarket ? (
          <button onClick={() => setAddingMarket(true)} style={{marginTop: 8}}>+ Link Another Market</button>
        ) : (
          <div className="add-market" style={{marginTop: 12}}>
            <div className="add-market-row">
              <select value={selectedMarket} onChange={e => setSelectedMarket(e.target.value)}>
                {otherMarkets.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <input placeholder="Search..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
              <button onClick={handleSearch}>Search</button>
              <button className="btn-danger btn-sm" onClick={() => setAddingMarket(false)}>Cancel</button>
            </div>
            <div className="add-market-row">
              <input placeholder="Or paste event ID" value={manualId} onChange={e => setManualId(e.target.value)} style={{flex:1}} />
              <button onClick={() => { if (manualId) handleAddMapping(manualId) }}>Add</button>
            </div>
            {searchResults.length > 0 && (
              <div className="search-results">
                {searchResults.map((r, i) => (
                  <div key={i} className="search-item" onClick={() => handleAddMapping(r.market_id)}>
                    <span>{r.title}</span><code>{r.market_id}</code>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {!orderBookData && !autoMatching && (
        <p className="empty">{wsConnected ? 'Waiting for data...' : 'Connecting...'}</p>
      )}

      {/* Outcome columns — each column = one outcome (Home/Away/Draw), rows = markets */}
      {columns.length > 0 && (
        <div className="outcome-columns">
          {columns.map(col => (
            <div key={col.outcome} className="outcome-col">
              <div className="outcome-col-header">{col.outcome}</div>
              {MARKET_ORDER.map(mname => {
                const ev = col.markets[mname]
                return (
                  <div key={mname} className="outcome-market-cell">
                    <div className="cell-market-label">{mname.toUpperCase()}</div>
                    {!ev || !ev.order_book ? (
                      <div className="cell-nodata">No Data</div>
                    ) : (
                      <div className="cell-ob">
                        <div className="cell-meta">
                          {ev.last_price != null && <span className="price">{(ev.last_price * 100).toFixed(1)}¢</span>}
                          {getBestBid(ev) != null && <span className="cell-bid">Bid: {(getBestBid(ev) * 100).toFixed(1)}¢</span>}
                          {getBestAsk(ev) != null && <span className="cell-ask">Ask: {(getBestAsk(ev) * 100).toFixed(1)}¢</span>}
                        </div>
                        <OrderBookChart orderBook={ev.order_book} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}

      {/* Spread Summary — per outcome, spread = best_bid + best_ask + best_draw across markets */}
      {columns.length > 0 && <SpreadSummary columns={columns} />}
    </div>
  )
}

function SpreadSummary({ columns }) {
  // Per market, per outcome: best bid price
  // Spread for a market = sum of best bids across all outcomes
  const marketSpreads = {}
  for (const mname of MARKET_ORDER) {
    const outcomeBids = {}
    for (const col of columns) {
      const ev = col.markets[mname]
      const bid = getBestBid(ev)
      outcomeBids[col.outcome] = bid
    }
    // Total spread = sum of all outcome best bids
    const values = Object.values(outcomeBids).filter(v => v != null)
    const totalSpread = values.length > 0 ? values.reduce((s, v) => s + v, 0) : null
    marketSpreads[mname] = { outcomeBids, totalSpread }
  }

  return (
    <div className="spread-summary">
      <h3>Spread Summary</h3>
      <p className="spread-formula">Spread = Best Bid (Home) + Best Bid (Away) + Best Bid (Draw)</p>
      <div className="outcome-columns spread-columns">
        {/* Per-outcome spread comparison */}
        {columns.map(col => (
          <div key={col.outcome} className="outcome-col spread-col">
            <div className="outcome-col-header">{col.outcome} — Best Bid</div>
            {MARKET_ORDER.map(mname => {
              const bid = marketSpreads[mname]?.outcomeBids[col.outcome]
              return (
                <div key={mname} className="spread-cell">
                  <span className="cell-market-label">{mname.toUpperCase()}</span>
                  <span className="spread-value">{bid != null ? `${(bid * 100).toFixed(2)}¢` : '—'}</span>
                </div>
              )
            })}
          </div>
        ))}
        {/* Total spread column */}
        <div className="outcome-col spread-col spread-total-col">
          <div className="outcome-col-header">Total Spread</div>
          {MARKET_ORDER.map(mname => {
            const total = marketSpreads[mname]?.totalSpread
            return (
              <div key={mname} className="spread-cell">
                <span className="cell-market-label">{mname.toUpperCase()}</span>
                <span className="spread-value spread-total">{total != null ? `${(total * 100).toFixed(2)}¢` : '—'}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
