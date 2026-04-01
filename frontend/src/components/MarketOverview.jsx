import React, { useState, useEffect } from 'react'
import { fetchOrderBooks } from '../api'

const PLATFORMS = ['btx', 'polymarket', 'kalshi', 'betfair']

// Get best bid/ask from an event's order_book
function getBestBid(ev) {
  if (!ev?.order_book?.bids?.length) return null
  return ev.order_book.bids[0].price
}
function getBestAsk(ev) {
  if (!ev?.order_book?.asks?.length) return null
  return ev.order_book.asks[0].price
}
function getTotalDepth(ev) {
  if (!ev?.order_book) return 0
  let d = 0
  for (const b of (ev.order_book.bids || [])) d += b.size
  for (const a of (ev.order_book.asks || [])) d += a.size
  return d
}

// Check if label is draw
function isDraw(label) {
  if (!label) return false
  const l = label.toLowerCase().trim()
  return l === 'draw' || l === 'the draw' || l === 'tie' || l.startsWith('draw (')
}

// Get display label for outcome
function getLabel(ev, platform) {
  if (platform === 'polymarket') return ev.event_title || ev.outcome || ''
  return ev.outcome || ev.event_title || ''
}

// Compute spread per platform: sum of best bids across all outcomes
function computeSpread(events, platform) {
  if (!events || !Array.isArray(events)) return null
  let total = 0
  let count = 0
  for (const ev of events) {
    const bid = getBestBid(ev)
    if (bid != null) { total += bid; count++ }
  }
  return count > 0 ? total : null
}

// Compute total liquidity (sum of all bid+ask sizes)
function computeLiquidity(events) {
  if (!events || !Array.isArray(events)) return 0
  let total = 0
  for (const ev of events) total += getTotalDepth(ev)
  return total
}

// Group BTX outcomes into canonical list, match other platforms
function getMarketTypes(marketsData) {
  const btxEvents = marketsData['btx'] || []
  if (btxEvents.length === 0) return []
  return btxEvents.map(ev => {
    const label = ev.outcome || ev.event_title || ''
    return { label, isDraw: isDraw(label) }
  })
}

export default function MarketOverview({ unifiedId, displayName, onSelectMarket, onBack }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchOrderBooks(unifiedId).then(d => {
      setData(d)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [unifiedId])

  if (loading) return <div className="detail-page"><p className="empty">Loading markets...</p></div>
  if (!data) return <div className="detail-page"><p className="empty">No data</p></div>

  const markets = data.markets || {}
  const marketTypes = getMarketTypes(markets)

  return (
    <div className="detail-page">
      <div className="detail-title-bar">
        <h2>{displayName || data.display_name}</h2>
        {data.event_time && <span className="detail-time">🕐 {new Date(data.event_time).toLocaleString()}</span>}
      </div>

      {/* Market comparison table */}
      <div className="mkt-table-wrap">
        <table className="mkt-table">
          <thead>
            <tr>
              <th className="mkt-th-outcome">Outcome</th>
              {PLATFORMS.map(p => (
                <th key={p} className="mkt-th-platform">{p.toUpperCase()}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {marketTypes.map((mt, idx) => (
              <tr key={idx} className="mkt-row">
                <td className="mkt-td-outcome">{mt.isDraw ? 'Draw' : mt.label}</td>
                {PLATFORMS.map(p => {
                  const events = markets[p]
                  if (!events || !Array.isArray(events) || events.length === 0) {
                    return <td key={p} className="mkt-td-cell mkt-td-empty">—</td>
                  }
                  // Find matching outcome
                  let matched = null
                  for (const ev of events) {
                    const evLabel = getLabel(ev, p)
                    const evDraw = isDraw(evLabel)
                    if (mt.isDraw && evDraw) { matched = ev; break }
                    if (!mt.isDraw && !evDraw) {
                      // Simple name match
                      const a = mt.label.toLowerCase().replace(/\b(fc|afc|sc)\b/g, '').trim()
                      const b = evLabel.toLowerCase().replace(/\b(fc|afc|sc)\b/g, '').trim()
                      if (a === b || a.includes(b) || b.includes(a)) { matched = ev; break }
                    }
                  }
                  if (!matched) return <td key={p} className="mkt-td-cell mkt-td-empty">—</td>

                  const bid = getBestBid(matched)
                  const ask = getBestAsk(matched)
                  const depth = getTotalDepth(matched)
                  return (
                    <td key={p} className="mkt-td-cell mkt-td-data"
                        onClick={() => onSelectMarket(mt.isDraw ? 'Draw' : mt.label)}
                        role="button" tabIndex={0}>
                      <div className="mkt-cell-bid">Bid: {bid != null ? `${(bid*100).toFixed(1)}¢` : '—'}</div>
                      <div className="mkt-cell-ask">Ask: {ask != null ? `${(ask*100).toFixed(1)}¢` : '—'}</div>
                      <div className="mkt-cell-depth">Depth: ${depth.toFixed(0)}</div>
                    </td>
                  )
                })}
              </tr>
            ))}
            {/* Summary row */}
            <tr className="mkt-row mkt-row-summary">
              <td className="mkt-td-outcome mkt-td-summary-label">Total</td>
              {PLATFORMS.map(p => {
                const events = markets[p]
                const spread = computeSpread(events, p)
                const liq = computeLiquidity(events)
                return (
                  <td key={p} className="mkt-td-cell mkt-td-summary">
                    <div className="mkt-cell-spread">Spread: {spread != null ? `${(spread*100).toFixed(1)}¢` : '—'}</div>
                    <div className="mkt-cell-liq">Liquidity: ${liq.toFixed(0)}</div>
                  </td>
                )
              })}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
