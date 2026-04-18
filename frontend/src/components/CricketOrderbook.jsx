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

export default function CricketOrderbook({ platform, marketId, marketType }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showOdds, setShowOdds] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchCricketOrderbook(platform, marketId, marketType)
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [platform, marketId, marketType])

  if (loading) return <div className="detail-page"><p className="empty">Loading orderbook...</p></div>
  if (!data) return <div className="detail-page"><p className="empty">No data</p></div>

  const markets = data.markets || {}
  const eventName = data.event_name || ''
  const displayMarketType = data.market_type || marketType || ''

  return (
    <div className="detail-page">
      <div className="detail-title-bar">
        <h2>{eventName}</h2>
        <div className="detail-title-meta">
          <span className="detail-time">🏏 Cricket{displayMarketType ? ` — ${displayMarketType}` : ''}</span>
          <button className="btn-toggle-odds" onClick={() => setShowOdds(!showOdds)}>
            {showOdds ? 'Show Predict Format' : 'Show Raw Data'}
          </button>
        </div>
      </div>

      {/* Each platform as a separate section, top to bottom */}
      {PLATFORM_ORDER.map(pname => {
        const mkt = markets[pname]
        const ob = mkt?.orderbook || []
        const hasOb = ob.length > 0
        const marketType = mkt?.type || mkt?.market_type || ''

        return (
          <div key={pname} className="cricket-platform-section">
            <div className="cricket-platform-header">
              <span className="cricket-platform-name">{(PLATFORM_DISPLAY[pname] || pname).toUpperCase()}</span>
              {marketType && <span className="cricket-market-type">{marketType}</span>}
            </div>

            {!mkt ? (
              <div className="outcome-market-cell"><div className="cell-nodata">No Data</div></div>
            ) : !hasOb ? (
              <div className="outcome-market-cell">
                <div className="cell-nodata">
                  {mkt.runners?.length > 0
                    ? `${mkt.runners.length} runner(s) — no live orderbook`
                    : 'No orderbook data'}
                </div>
              </div>
            ) : (
              <div className="outcome-columns" style={{gridTemplateColumns: `repeat(${ob.length}, 1fr)`}}>
                {/* Outcome headers */}
                {ob.map((ev, i) => (
                  <div key={i} className="outcome-col-header">
                    {ev.outcome || ev.event_title || `Outcome ${i + 1}`}
                  </div>
                ))}
                {/* Orderbook cells */}
                {ob.map((ev, i) => (
                  <div key={`ob-${i}`} className="outcome-market-cell">
                    {!ev.order_book ? (
                      <div className="cell-nodata">No Data</div>
                    ) : (
                      <div className="cell-ob">
                        <ShowSubHeader ev={ev} mname={pname} showOdds={showOdds} />
                        <OrderBookChart orderBook={ev.order_book} showOdds={showOdds} marketName={pname} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}

      <CricketLiquiditySummary markets={markets} />
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

function CricketLiquiditySummary({ markets }) {
  const stats = {}
  for (const mname of PLATFORM_ORDER) {
    let availLiq = 0, availVol = 0, matchedLiq = 0, hasMatched = false, spreadSum = 0, spreadCount = 0
    const ob = markets[mname]?.orderbook || []
    for (const ev of ob) {
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
