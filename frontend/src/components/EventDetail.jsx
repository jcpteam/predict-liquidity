import React, { useState, useEffect, useRef } from 'react'
import { fetchEventMapping, addMarketMapping, removeMarketMapping, searchMarketEvents, fetchOrderBooks, autoMatchMarket } from '../api'
import OrderBookChart from './OrderBookChart.jsx'

const MARKET_ORDER = ['polymarket', 'kalshi', 'betfair']

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
  const [loadingOB, setLoadingOB] = useState(false)
  const [autoMatching, setAutoMatching] = useState(false)
  const [addingMarket, setAddingMarket] = useState(false)
  const [selectedMarket, setSelectedMarket] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [manualId, setManualId] = useState('')
  const matchAttemptedRef = useRef(false)

  // Load mapping
  useEffect(() => {
    setOrderBookData(null)
    matchAttemptedRef.current = false
    fetchEventMapping(unifiedId).then(setMapping)
  }, [unifiedId])

  // Auto-match unlinked markets on mount, then load order books
  useEffect(() => {
    if (!mapping) return
    const otherMarkets = markets.filter(m => m !== 'polymarket')
    const unlinked = otherMarkets.filter(m => !mapping.mappings[m])

    const doAutoMatchAndLoad = async () => {
      if (unlinked.length > 0 && !matchAttemptedRef.current) {
        matchAttemptedRef.current = true
        setAutoMatching(true)
        try {
          for (const m of unlinked) {
            await autoMatchMarket(m)
          }
          const updated = await fetchEventMapping(unifiedId)
          setMapping(updated)
          onMappingChange()
        } catch (e) {
          console.error('Auto-match failed:', e)
        } finally {
          setAutoMatching(false)
        }
      }
      // Load order books
      setLoadingOB(true)
      try {
        const data = await fetchOrderBooks(unifiedId)
        setOrderBookData(data)
      } catch (e) {
        console.error('Failed to load order books:', e)
      } finally {
        setLoadingOB(false)
      }
    }
    doAutoMatchAndLoad()
  }, [mapping?.unified_id])

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
    // Reload order books
    setLoadingOB(true)
    try {
      const data = await fetchOrderBooks(unifiedId)
      setOrderBookData(data)
    } catch (e) { console.error(e) }
    finally { setLoadingOB(false) }
  }

  const handleRemove = async (marketName) => {
    await removeMarketMapping(unifiedId, marketName)
    const updated = await fetchEventMapping(unifiedId)
    setMapping(updated)
    onMappingChange()
  }

  if (!mapping) return <div className="detail-page"><p>Loading...</p></div>

  const marketNames = orderBookData ? sortMarketNames(Object.keys(orderBookData.markets || {})) : []

  return (
    <div className="detail-page">
      <div className="detail-title-bar">
        <h2>{mapping.display_name}</h2>
        <div className="detail-title-meta">
          {mapping.event_time && <span className="detail-time">🕐 {new Date(mapping.event_time).toLocaleString()}</span>}
          {autoMatching && <span className="auto-match-status">🔄 Auto-matching markets...</span>}
          {loadingOB && <span className="auto-match-status">📊 Loading order books...</span>}
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

      {/* Order Books - one market per row, outcomes horizontal */}
      {!loadingOB && !orderBookData && !autoMatching && (
        <p className="empty">No order book data available.</p>
      )}

      {marketNames.map(mname => {
        const events = orderBookData.markets[mname]
        if (!events || events.length === 0) return null
        const hasError = events.length === 1 && events[0].error
        return (
          <div key={mname} className="market-row">
            <div className="market-row-header">
              <h3>{mname.toUpperCase()}</h3>
              <span className="market-row-meta">{events.length} outcome{events.length > 1 ? 's' : ''}</span>
            </div>
            {hasError ? (
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

      {/* Liquidity summary */}
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
