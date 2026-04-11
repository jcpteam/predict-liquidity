import React, { useState, useEffect, useRef, useCallback } from 'react'
import { fetchEventMapping, addMarketMapping, removeMarketMapping, searchMarketEvents, autoMatchMarket, createOrderBookSocket } from '../api'
import OrderBookChart from './OrderBookChart.jsx'

const MARKET_ORDER = ['btx', 'polymarket', 'kalshi', 'betfair']

// Get the display label for an outcome event
// Polymarket: outcome is always "Yes", real info is in event_title
// Others: outcome is the team name or "Draw"
function getOutcomeLabel(ev, marketName) {
  if (marketName === 'polymarket') {
    // event_title is like "Liverpool FC" or "Draw (Liverpool FC vs. Fulham FC)"
    return ev.event_title || ev.outcome || ''
  }
  return ev.outcome || ev.event_title || ''
}

// Check if a label represents a draw
function isDraw(label) {
  if (!label) return false
  const l = label.toLowerCase().trim()
  return l === 'draw' || l === 'the draw' || l === 'tie' || l === 'x' || l.startsWith('draw (') || l.startsWith('draw(')
}

// Normalize a label for matching: lowercase, strip common suffixes
function normLabel(label) {
  if (!label) return ''
  let s = label.toLowerCase().trim()
  s = s.replace(/\b(fc|afc|sc|ac|cf|cd|fk|nk|sk)\b/gi, '').trim()
  s = s.replace(/[.\-]+$/, '').replace(/^[.\-]+/, '').trim()
  s = s.replace(/\s+/g, ' ')
  return s
}

// Common football team aliases
const TEAM_ALIASES = {
  'wolves': 'wolverhampton',
  'wolverhampton wanderers': 'wolverhampton',
  'spurs': 'tottenham',
  'tottenham hotspur': 'tottenham',
  'man utd': 'manchester united',
  'man united': 'manchester united',
  'man city': 'manchester city',
  'nottm forest': 'nottingham forest',
  'nott forest': 'nottingham forest',
  'brighton and hove albion': 'brighton',
  'brighton hove albion': 'brighton',
  'west ham united': 'west ham',
  'newcastle united': 'newcastle',
  'leicester city': 'leicester',
  'sheffield united': 'sheffield',
  'crystal palace': 'crystal palace',
  'atletico de madrid': 'atletico',
  'atletico madrid': 'atletico',
  'real madrid': 'real madrid',
  'barcelona': 'barcelona',
  'bayern munchen': 'bayern munich',
  'bayern münchen': 'bayern munich',
  'borussia dortmund': 'dortmund',
  'paris saint germain': 'psg',
  'paris saint-germain': 'psg',
  'inter milan': 'inter',
  'internazionale': 'inter',
  'ac milan': 'milan',
}

function resolveAlias(name) {
  const n = normLabel(name)
  return TEAM_ALIASES[n] || n
}

// Simple word overlap similarity with alias resolution
function labelSimilarity(a, b) {
  if (!a || !b) return 0
  const na = resolveAlias(a)
  const nb = resolveAlias(b)
  if (na === nb) return 1
  if (na.includes(nb) || nb.includes(na)) return 0.85
  const wa = new Set(na.split(' '))
  const wb = new Set(nb.split(' '))
  const inter = [...wa].filter(w => wb.has(w)).length
  const union = new Set([...wa, ...wb]).size
  return union > 0 ? inter / union : 0
}

// Group outcomes across markets into columns
function buildOutcomeColumns(marketsData) {
  // Step 1: Build canonical outcome list from BTX (primary) or first market with data
  const canonicalOutcomes = [] // [{label, isDrawFlag}]
  for (const mname of MARKET_ORDER) {
    const events = marketsData[mname]
    if (!events || !Array.isArray(events) || events.length === 0) continue
    for (const ev of events) {
      const label = getOutcomeLabel(ev, mname)
      canonicalOutcomes.push({ label, isDraw: isDraw(label) })
    }
    break // Use first market with data as canonical
  }

  if (canonicalOutcomes.length === 0) return []

  // Step 2: For each canonical outcome, find best match in each market
  return canonicalOutcomes.map(canon => {
    const col = { outcome: canon.isDraw ? 'Draw' : canon.label, markets: {} }

    for (const mname of MARKET_ORDER) {
      const events = marketsData[mname]
      if (!events || !Array.isArray(events) || events.length === 0) {
        col.markets[mname] = null
        continue
      }

      // Find best matching event
      let bestEv = null
      let bestScore = -1

      for (const ev of events) {
        const evLabel = getOutcomeLabel(ev, mname)
        const evIsDraw = isDraw(evLabel)

        // Draw matches draw
        if (canon.isDraw && evIsDraw) {
          bestEv = ev
          bestScore = 1
          break
        }
        // Non-draw: compare by name similarity
        if (!canon.isDraw && !evIsDraw) {
          const sim = labelSimilarity(canon.label, evLabel)
          if (sim > bestScore) {
            bestScore = sim
            bestEv = ev
          }
        }
      }

      col.markets[mname] = bestScore >= 0.2 ? bestEv : null
    }

    return col
  })
}

// Get best bid price (highest) for an outcome event
function getBestBid(ev) {
  if (!ev || !ev.order_book || !ev.order_book.bids || !ev.order_book.bids.length) return null
  return Math.max(...ev.order_book.bids.map(b => b.price))
}
function getBestAsk(ev) {
  if (!ev || !ev.order_book || !ev.order_book.asks || !ev.order_book.asks.length) return null
  return Math.min(...ev.order_book.asks.map(a => a.price))
}
// For spread: use last_price if available (more accurate), else best bid
function getSpreadPrice(ev) {
  if (!ev) return null
  if (ev.last_price != null && ev.last_price > 0 && ev.last_price < 1) return ev.last_price
  return getBestBid(ev)
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
  const [showOdds, setShowOdds] = useState(false)
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
        <button className="btn-toggle-odds" onClick={() => setShowOdds(!showOdds)}>
          {showOdds ? 'Show Probabilities' : 'Show Odds'}
        </button>
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

      {/* Outcome columns — each column = one outcome, rows = markets */}
      {columns.length > 0 && (
        <div className="outcome-columns">
          {columns.map(col => (
            <div key={col.outcome} className="outcome-col-header">{col.outcome}</div>
          ))}

          {MARKET_ORDER.map(mname => (
            columns.map(col => {
              const ev = col.markets[mname]
              return (
                <div key={`${col.outcome}-${mname}`} className="outcome-market-cell">
                  <div className="cell-market-label">{mname.toUpperCase()}</div>
                  {!ev || !ev.order_book ? (
                    <div className="cell-nodata">No Data</div>
                  ) : (
                    <div className="cell-ob">
                        <ShowSubHeader ev={ev} showOdds={showOdds} />
                        <OrderBookChart orderBook={ev.order_book} showOdds={showOdds} />
                    </div>
                  )}
                </div>
              )
            })
          ))}
        </div>
      )}

      {columns.length > 0 && <LiquiditySummary columns={columns} />}
    </div>
  )
}

function ShowSubHeader ({ev,showOdds}){

  return (
      <div className="cell-meta">
        {ev.last_price != null && <span className="price">{showOdds ? (ev.last_price > 0 ? (1 / ev.last_price).toFixed(2) : '—') : (ev.last_price * 100).toFixed(1) + '¢'}</span>}
        {getBestBid(ev) != null && <span className="cell-bid">Bid: {showOdds ? (getBestBid(ev) > 0 ? (1 / getBestBid(ev)).toFixed(2) : '—') : (getBestBid(ev) * 100).toFixed(1) + '¢'}</span>}
        {getBestAsk(ev) != null && <span className="cell-ask">Ask: {showOdds ? (getBestAsk(ev) > 0 ? (1 / getBestAsk(ev)).toFixed(2) : '—') : (getBestAsk(ev) * 100).toFixed(1) + '¢'}</span>}
      </div>
  )
}

function LiquiditySummary({ columns }) {
  const stats = {}
  for (const mname of MARKET_ORDER) {
    let availLiq = 0, availVol = 0, matchedLiq = 0, hasMatched = false, bidSum = 0, bidCount = 0
    for (const col of columns) {
      const ev = col.markets[mname]
      if (ev && ev.order_book) {
        const bids = ev.order_book.bids || []
        const asks = ev.order_book.asks || []
        availLiq += bids.reduce((s, b) => s + b.size, 0) + asks.reduce((s, a) => s + a.size, 0)
        availVol += bids.reduce((s, b) => s + b.size * b.price, 0) + asks.reduce((s, a) => s + a.size * a.price, 0)
        if (bids.length) {
          // Use last_price for spread if available (avoids outlier bids)
          const spreadPrice = getSpreadPrice(ev)
          if (spreadPrice != null) { bidSum += spreadPrice; bidCount++ }
        }
      }
      if (ev && ev.volume_24h != null) { matchedLiq += Number(ev.volume_24h); hasMatched = true }
    }
    stats[mname] = { availLiq, availVol, matchedLiq: hasMatched ? matchedLiq : null, overround: bidCount > 0 ? bidSum : null }
  }

  return (
    <div className="liquidity-summary">
      <h3>Summary</h3>
      <div className="liq-formulas">
        <p>Available Liquidity = Σ(bid sizes + ask sizes)</p>
        <p>Available Volume = Σ(size × probability)</p>
        <p>Matched Liquidity / Volume = Traded amount from exchange</p>
        <p>Spread = Last Price(Home) + Last Price(Away) + Last Price(Draw). Fair market = 100¢</p>
      </div>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            {MARKET_ORDER.map(m => <th key={m}>{m.toUpperCase()}</th>)}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td title="Σ(bid sizes + ask sizes)">Available Liquidity</td>
            {MARKET_ORDER.map(m => <td key={m}>${stats[m].availLiq.toFixed(0)}</td>)}
          </tr>
          <tr>
            <td title="Σ(size × price)">Available Volume</td>
            {MARKET_ORDER.map(m => <td key={m}>${stats[m].availVol.toFixed(0)}</td>)}
          </tr>
          <tr>
            <td>Matched Liquidity</td>
            {MARKET_ORDER.map(m => <td key={m} className="matched-val">{stats[m].matchedLiq != null ? `$${stats[m].matchedLiq.toFixed(0)}` : '—'}</td>)}
          </tr>
          <tr>
            <td>Matched Volume</td>
            {MARKET_ORDER.map(m => <td key={m} className="matched-val">{stats[m].matchedLiq != null ? `$${stats[m].matchedLiq.toFixed(0)}` : '—'}</td>)}
          </tr>
          <tr className="overround-row">
            <td title="Spread = Σ Last Price (or Best Bid if no last price). Fair market = 100¢">Spread</td>
            {MARKET_ORDER.map(m => <td key={m}>{stats[m].overround != null ? `${(stats[m].overround * 100).toFixed(1)}¢` : '—'}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  )
}
