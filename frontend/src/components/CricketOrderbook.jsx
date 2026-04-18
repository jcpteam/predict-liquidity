import React, { useState, useEffect } from 'react'
import { fetchCricketOrderbook } from '../api'
import OrderBookChart from './OrderBookChart.jsx'

const PLATFORM_ORDER = ['btx', 'polymarket', 'kalshi']
const PLATFORM_DISPLAY = { btx: 'BTX', polymarket: 'POLYMARKET', kalshi: 'KALSHI' }

function getBestBid(ev) {
  if (!ev?.order_book?.bids?.length) return null
  return Math.max(...ev.order_book.bids.map(b => b.price))
}
function getBestAsk(ev) {
  if (!ev?.order_book?.asks?.length) return null
  return Math.min(...ev.order_book.asks.map(a => a.price))
}
function getSpreadPrice(ev, mname) {
  if (!ev) return null
  if (mname === 'btx') return getBestAsk(ev)
  if (ev.last_price != null && ev.last_price > 0 && ev.last_price < 1) return ev.last_price
  return getBestBid(ev)
}

function normLabel(s) {
  if (!s) return ''
  return s.toLowerCase().replace(/\s+/g, ' ').trim()
}

function labelSimilarity(a, b) {
  if (!a || !b) return 0
  const na = normLabel(a), nb = normLabel(b)
  if (na === nb) return 1
  if (na.includes(nb) || nb.includes(na)) return 0.85
  const wa = new Set(na.split(' ')), wb = new Set(nb.split(' '))
  const inter = [...wa].filter(w => wb.has(w)).length
  const union = new Set([...wa, ...wb]).size
  return union > 0 ? inter / union : 0
}

/**
 * Build outcome columns from cricket orderbook data.
 * Structure: markets[platform].orderbook[] — each entry has outcome/event_title + order_book
 * We align outcomes across platforms by name similarity (same as football).
 */
function buildOutcomeColumns(markets) {
  // Find canonical outcomes from first platform with orderbook data
  const canonicalOutcomes = []
  for (const mname of PLATFORM_ORDER) {
    const ob = markets[mname]?.orderbook || []
    if (ob.length === 0) continue
    for (const ev of ob) {
      canonicalOutcomes.push(ev.outcome || ev.event_title || `Outcome`)
    }
    break
  }
  if (canonicalOutcomes.length === 0) return []

  return canonicalOutcomes.map(label => {
    const col = { outcome: label, markets: {} }
    for (const mname of PLATFORM_ORDER) {
      const ob = markets[mname]?.orderbook || []
      if (ob.length === 0) { col.markets[mname] = null; continue }
      let bestEv = null, bestScore = -1
      for (const ev of ob) {
        const evLabel = ev.outcome || ev.event_title || ''
        const sim = labelSimilarity(label, evLabel)
        if (sim > bestScore) { bestScore = sim; bestEv = ev }
      }
      col.markets[mname] = bestScore >= 0.2 ? bestEv : null
    }
    return col
  })
}

export default function CricketOrderbook({ platform, marketId, onBack }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showOdds, setShowOdds] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchCricketOrderbook(platform, marketId)
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [platform, marketId])

  if (loading) return <div className="detail-page"><p className="empty">Loading orderbook...</p></div>
  if (!data) return <div className="detail-page"><p className="empty">No data</p></div>

  const markets = data.markets || {}
  const eventName = data.event_name || ''
  const columns = buildOutcomeColumns(markets)

  return (
    <div className="detail-page">
      <div className="detail-title-bar">
        <h2>{eventName}</h2>
        <div className="detail-title-meta">
          <span className="detail-time">🏏 Cricket</span>
          <button className="btn-toggle-odds" onClick={() => setShowOdds(!showOdds)}>
            {showOdds ? 'Show Predict Format' : 'Show Raw Data'}
          </button>
        </div>
      </div>

      {columns.length === 0 && <p className="empty">No orderbook data</p>}

      {/* Outcome columns grid — same layout as football: columns=outcomes, rows=platforms */}
      {columns.length > 0 && (
        <div className="outcome-columns">
          {columns.map(col => (
            <div key={col.outcome} className="outcome-col-header">{col.outcome}</div>
          ))}

          {PLATFORM_ORDER.map(mname => (
            columns.map(col => {
              const ev = col.markets[mname]
              return (
                <div key={`${col.outcome}-${mname}`} className="outcome-market-cell">
                  <div className="cell-market-label">{(PLATFORM_DISPLAY[mname] || mname).toUpperCase()}</div>
                  {!ev || !ev.order_book ? (
                    <div className="cell-nodata">No Data</div>
                  ) : (
                    <div className="cell-ob">
                      <ShowSubHeader ev={ev} mname={mname} showOdds={showOdds} />
                      <OrderBookChart orderBook={ev.order_book} showOdds={showOdds} marketName={mname} />
                    </div>
                  )}
                </div>
              )
            })
          ))}
        </div>
      )}

      {columns.length > 0 && <CricketLiquiditySummary columns={columns} />}
    </div>
  )
}

function ShowSubHeader({ ev, mname, showOdds }) {
  const isExchange = mname === 'btx'
  const fmtPrice = (p) => {
    if (p == null) return '—'
    if (showOdds && isExchange && p > 0) return (1 / p).toFixed(2)
    return (p * 100).toFixed(1) + '¢'
  }
  const bestBid = getBestBid(ev)
  const bestAsk = getBestAsk(ev)
  let displayPrice
  if (mname === 'btx' && bestAsk != null) displayPrice = bestAsk
  else if (mname === 'polymarket' && bestAsk != null) displayPrice = bestAsk
  else displayPrice = ev.last_price ?? bestBid

  return (
    <div className="cell-meta">
      <span className="price">{fmtPrice(displayPrice)}</span>
      {bestBid != null && <span className="cell-bid">Bid: {fmtPrice(bestBid)}</span>}
      {bestAsk != null && <span className="cell-ask">Ask: {fmtPrice(bestAsk)}</span>}
    </div>
  )
}

function CricketLiquiditySummary({ columns }) {
  const stats = {}
  for (const mname of PLATFORM_ORDER) {
    let availLiq = 0, availVol = 0, matchedLiq = 0, hasMatched = false, spreadSum = 0, spreadCount = 0
    for (const col of columns) {
      const ev = col.markets[mname]
      if (ev?.order_book) {
        const bids = ev.order_book.bids || []
        const asks = ev.order_book.asks || []
        availLiq += bids.reduce((s, b) => s + b.size, 0) + asks.reduce((s, a) => s + a.size, 0)
        availVol += bids.reduce((s, b) => s + b.size * b.price, 0) + asks.reduce((s, a) => s + a.size * a.price, 0)
        const sp = getSpreadPrice(ev, mname)
        if (sp != null) { spreadSum += sp; spreadCount++ }
      }
      if (ev?.volume_24h != null) { matchedLiq += Number(ev.volume_24h); hasMatched = true }
    }
    stats[mname] = { availLiq, availVol, matchedLiq: hasMatched ? matchedLiq : null, overround: spreadCount > 0 ? spreadSum : null }
  }

  return (
    <div className="liquidity-summary">
      <h3>Summary</h3>
      <div className="liq-formulas">
        <p>Available Liquidity = Σ(bid sizes + ask sizes)</p>
        <p>Available Volume = Σ(sizes × probability)</p>
        <p>Matched Liquidity = 24h traded volume (PM: USDC, Kalshi: USD, BTX: USD)</p>
        <p>Spread = Σ Last Price per outcome. Fair market = 100¢</p>
      </div>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            {PLATFORM_ORDER.map(m => <th key={m}>{(PLATFORM_DISPLAY[m] || m).toUpperCase()}</th>)}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td title="Σ(bid sizes + ask sizes)">Available Liquidity</td>
            {PLATFORM_ORDER.map(m => <td key={m}>{stats[m].availLiq.toFixed(0)}</td>)}
          </tr>
          <tr>
            <td title="Σ(sizes × probability)">Available Volume</td>
            {PLATFORM_ORDER.map(m => <td key={m}>{stats[m].availVol.toFixed(0)}</td>)}
          </tr>
          <tr>
            <td>Matched Liquidity</td>
            {PLATFORM_ORDER.map(m => <td key={m} className="matched-val">{stats[m].matchedLiq != null ? stats[m].matchedLiq.toFixed(0) : '—'}</td>)}
          </tr>
          <tr>
            <td title="Spread = Σ Last Price per outcome. Fair market = 100¢">Spread</td>
            {PLATFORM_ORDER.map(m => <td key={m}>{stats[m].overround != null ? `${(stats[m].overround * 100).toFixed(1)}¢` : '—'}</td>)}
          </tr>
        </tbody>
      </table>
      <div className="liq-formulas" style={{marginTop: 8}}>
        <p>Raw → Predict: probability = 1 / decimal_odds × 100 (¢)</p>
        <p>Predict → Raw: decimal_odds = 1 / (probability / 100)</p>
        <p>Example: odds 2.50 → 1/2.50 = 0.40 = 40.0¢ | 40.0¢ → 1/0.40 = 2.50</p>
      </div>
    </div>
  )
}
