import React, { useState, useEffect, useRef, useCallback } from 'react'
import { fetchEventMapping, addMarketMapping, removeMarketMapping, searchMarketEvents, autoMatchMarket, createOrderBookSocket } from '../api'
import OrderBookChart from './OrderBookChart.jsx'

const MARKET_ORDER = ['btx', 'polymarket', 'kalshi', 'betfair']

function sortMarketNames(names) {
  return [...names].sort((a, b) => {
    const ia = MARKET_ORDER.indexOf(a)
    const ib = MARKET_ORDER.indexOf(b)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })
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

  // Close WS on unmount or unifiedId change
  const closeWs = useCallback(() => {
    if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = null }
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null }
    setWsConnected(false)
  }, [])

  // Connect WebSocket
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
          // Find matching outcome and update its order_book
          for (let i = 0; i < pmEvents.length; i++) {
            const ev = pmEvents[i]
            if (ev.outcome === data.outcome || ev.event_title === data.title) {
              pmEvents[i] = { ...ev, order_book: { bids: data.bids, asks: data.asks } }
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
      onTrade: (data) => {
        setLastUpdate(new Date())
      },
      onKalshiUpdate: (data) => {
        setOrderBookData(prev => {
          if (!prev) return prev
          return { ...prev, markets: { ...prev.markets, kalshi: data.events } }
        })
        setLastUpdate(new Date())
      },
      onBetfairUpdate: (data) => {
        setOrderBookData(prev => {
          if (!prev) return prev
          return { ...prev, markets: { ...prev.markets, betfair: data.events } }
        })
        setLastUpdate(new Date())
      },
      onBtxUpdate: (data) => {
        setOrderBookData(prev => {
          if (!prev) return prev
          return { ...prev, markets: { ...prev.markets, btx: data.events } }
        })
        setLastUpdate(new Date())
      },
      onOpen: () => setWsConnected(true),
      onClose: () => {
        setWsConnected(false)
        // Auto-reconnect after 3s
        reconnectTimer.current = setTimeout(() => connectWs(uid), 3000)
      },
      onError: (msg) => console.error('[ws]', msg),
    })
    wsRef.current = ws
  }, [closeWs])

  // Load mapping
  useEffect(() => {
    setOrderBookData(null)
    matchAttemptedRef.current = false
    closeWs()
    fetchEventMapping(unifiedId).then(setMapping)
    return () => closeWs()
  }, [unifiedId, closeWs])

  // Auto-match then connect WS
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
      // Connect WebSocket for real-time data
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
    // Reconnect WS to pick up new market
    connectWs(unifiedId)
  }

  const handleRemove = async (marketName) => {
    await removeMarketMapping(unifiedId, marketName)
    const updated = await fetchEventMapping(unifiedId)
    setMapping(updated)
    onMappingChange()
  }

  if (!mapping) return <div className="detail-page"><p>Loading...</p></div>

  const marketNames = orderBookData ? MARKET_ORDER : []

  return (
    <div className="detail-page">
      <div className="detail-title-bar">
        <h2>{mapping.display_name}</h2>
        <div className="detail-title-meta">
          {mapping.event_time && <span className="detail-time">🕐 {new Date(mapping.event_time).toLocaleString()}</span>}
          {wsConnected ? (
            <span className="live-dot">● LIVE</span>
          ) : (
            <span className="auto-match-status">○ Connecting...</span>
          )}
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
              {name !== 'btx' && (
                <button className="btn-danger btn-sm" onClick={() => handleRemove(name)}>✕</button>
              )}
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
                    <span>{r.title}</span>
                    <code>{r.market_id}</code>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Order Books */}
      {!orderBookData && !autoMatching && (
        <p className="empty">{wsConnected ? 'Waiting for data...' : 'Connecting...'}</p>
      )}

      {marketNames.map(mname => {
        const events = orderBookData.markets[mname]
        const hasData = events && events.length > 0
        const hasError = hasData && events.length === 1 && events[0].error
        return (
          <div key={mname} className="market-row">
            <div className="market-row-header">
              <h3>{mname.toUpperCase()}</h3>
              {hasData && <span className="market-row-meta">{events.length} outcome{events.length > 1 ? 's' : ''}</span>}
            </div>
            {!hasData ? (
              <div className="market-row-nodata">No Data</div>
            ) : hasError ? (
              <p className="error">{events[0].error}</p>
            ) : (
              <div className="market-row-cards">
                {events.map((ev, i) => (
                  <div key={i} className="ob-card">
                    {ev.event_title && <div className="ob-card-title">{ev.event_title}</div>}
                    <div className="ob-card-meta">
                      <span className="outcome-label">{ev.outcome}</span>
                      {ev.last_price != null && <span className="price">{(ev.last_price * 100).toFixed(1)}¢</span>}
                      {ev.volume_24h != null && <span className="volume">Vol: ${Number(ev.volume_24h).toLocaleString()}</span>}
                    </div>
                    {ev.order_book && <OrderBookChart orderBook={ev.order_book} />}
                    {ev.error && <p className="error">{ev.error}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {marketNames.length >= 2 && orderBookData && <LiquiditySummary data={orderBookData} />}
    </div>
  )
}

function LiquiditySummary({ data }) {
  const summary = Object.entries(data.markets).map(([name, events]) => {
    let totalBidDepth = 0, totalAskDepth = 0, bestBid = 0, bestAsk = 1
    for (const ev of events) {
      if (ev.order_book) {
        for (const b of ev.order_book.bids) totalBidDepth += b.size * b.price
        for (const a of ev.order_book.asks) totalAskDepth += a.size * a.price
        if (ev.order_book.bids.length) bestBid = Math.max(bestBid, ev.order_book.bids[0].price)
        if (ev.order_book.asks.length) bestAsk = Math.min(bestAsk, ev.order_book.asks[0].price)
      }
    }
    return { name, totalBidDepth, totalAskDepth, spread: bestAsk - bestBid }
  })

  return (
    <div className="liquidity-summary">
      <h3>Liquidity Summary</h3>
      <table>
        <thead>
          <tr><th>Market</th><th>Bid Depth ($)</th><th>Ask Depth ($)</th><th>Spread</th></tr>
        </thead>
        <tbody>
          {summary.map(s => (
            <tr key={s.name}>
              <td>{s.name}</td>
              <td>${s.totalBidDepth.toFixed(2)}</td>
              <td>${s.totalAskDepth.toFixed(2)}</td>
              <td>{(s.spread * 100).toFixed(2)}¢</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
