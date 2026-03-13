import React, { useState, useEffect, useRef } from 'react'
import { fetchEventMapping, addMarketMapping, removeMarketMapping, searchMarketEvents, createLiveSocket } from '../api'
import OrderBookChart from './OrderBookChart.jsx'

export default function EventDetail({ unifiedId, markets, onMappingChange }) {
  const [mapping, setMapping] = useState(null)
  const [liveData, setLiveData] = useState(null)
  const [addingMarket, setAddingMarket] = useState(false)
  const [selectedMarket, setSelectedMarket] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [manualId, setManualId] = useState('')
  const wsRef = useRef(null)

  // 加载映射
  useEffect(() => {
    setLiveData(null)
    fetchEventMapping(unifiedId).then(setMapping)
  }, [unifiedId])

  // WebSocket 实时 order book
  useEffect(() => {
    if (wsRef.current) wsRef.current.close()
    const ws = createLiveSocket(unifiedId, (msg) => {
      if (!msg.error) setLiveData(msg)
    })
    wsRef.current = ws
    return () => ws.close()
  }, [unifiedId])

  const otherMarkets = markets.filter(m => m !== 'polymarket')

  useEffect(() => {
    if (otherMarkets.length > 0 && !selectedMarket) {
      setSelectedMarket(otherMarkets[0])
    }
  }, [markets])

  const handleSearch = async () => {
    if (!selectedMarket) return
    const results = await searchMarketEvents(selectedMarket, searchQuery)
    setSearchResults(results)
  }

  const handleAddMapping = async (marketEventId) => {
    await addMarketMapping(unifiedId, selectedMarket, marketEventId)
    setSearchResults([])
    setManualId('')
    setAddingMarket(false)
    const updated = await fetchEventMapping(unifiedId)
    setMapping(updated)
    onMappingChange()
  }

  const handleRemove = async (marketName) => {
    await removeMarketMapping(unifiedId, marketName)
    const updated = await fetchEventMapping(unifiedId)
    setMapping(updated)
    onMappingChange()
  }

  if (!mapping) return <div className="detail-panel"><p>Loading...</p></div>

  const marketNames = liveData ? Object.keys(liveData.markets || {}) : []

  return (
    <div className="detail-panel">
      <h2>{mapping.display_name}</h2>
      {mapping.event_time && (
        <p className="timestamp">Event: {new Date(mapping.event_time).toLocaleString()}</p>
      )}

      {/* 已关联的市场 */}
      <div className="linked-section">
        <h3>Linked Markets</h3>
        <div className="linked-list">
          {Object.entries(mapping.mappings).map(([name, id]) => (
            <div key={name} className="linked-item">
              <span className="market-badge">{name}</span>
              <code>{id}</code>
              {name !== 'polymarket' && (
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

      {/* Order Book 对比 */}
      <div className="comparison-section">
        <h3>📊 Order Book Comparison {liveData && <span className="live-dot">● LIVE</span>}</h3>
        {liveData && <p className="timestamp">Last update: {new Date(liveData.timestamp).toLocaleTimeString()}</p>}
        {!liveData && <p className="empty">Connecting to live feed...</p>}

        {marketNames.length > 0 && (
          <div className="comparison-grid">
            {marketNames.map(mname => {
              const events = liveData.markets[mname]
              if (!events || events.length === 0) return null
              return (
                <div key={mname} className="market-column">
                  <h3 className="market-header">{mname.toUpperCase()}</h3>
                  {events.map((ev, i) => (
                    <div key={i} className="event-card">
                      <div className="event-meta">
                        <span className="outcome-label">{ev.outcome}</span>
                        {ev.last_price != null && <span className="price">{(ev.last_price * 100).toFixed(1)}¢</span>}
                        {ev.volume_24h != null && <span className="volume">Vol: ${Number(ev.volume_24h).toLocaleString()}</span>}
                      </div>
                      {ev.order_book && <OrderBookChart orderBook={ev.order_book} />}
                      {ev.error && <p className="error">{ev.error}</p>}
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        )}

        {marketNames.length >= 2 && <LiquiditySummary data={liveData} />}
      </div>
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
