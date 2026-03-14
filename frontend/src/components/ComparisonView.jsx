import React, { useState, useEffect, useRef } from 'react'
import { createLiveSocket } from '../api'
import OrderBookChart from '../../../prediction-market-liquidity/frontend/src/components/OrderBookChart.jsx'

export default function ComparisonView({ unifiedId }) {
  const [data, setData] = useState(null)
  const wsRef = useRef(null)

  useEffect(() => {
    if (wsRef.current) wsRef.current.close()
    const ws = createLiveSocket(unifiedId, (msg) => {
      if (msg.error) {
        console.error(msg.error)
        return
      }
      setData(msg)
    })
    wsRef.current = ws
    return () => ws.close()
  }, [unifiedId])

  if (!data) return <section className="panel"><p>Connecting to live feed...</p></section>

  const marketNames = Object.keys(data.markets || {})

  return (
    <section className="panel">
      <h2>📊 Live Comparison: {data.display_name}</h2>
      <p className="timestamp">Last update: {new Date(data.timestamp).toLocaleTimeString()}</p>

      {marketNames.length === 0 && <p className="empty">No markets linked. Add markets above to see comparison.</p>}

      <div className="comparison-grid">
        {marketNames.map(mname => {
          const events = data.markets[mname]
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

      {marketNames.length >= 2 && <LiquiditySummary data={data} />}
    </section>
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
