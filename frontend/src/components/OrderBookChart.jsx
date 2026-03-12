import React from 'react'

export default function OrderBookChart({ orderBook }) {
  if (!orderBook) return null

  const bids = orderBook.bids.slice(0, 10)
  const asks = orderBook.asks.slice(0, 10)
  const maxSize = Math.max(
    ...bids.map(b => b.size),
    ...asks.map(a => a.size),
    1
  )

  return (
    <div className="order-book">
      <div className="ob-side ob-bids">
        <div className="ob-label">BIDS</div>
        {bids.map((b, i) => (
          <div key={i} className="ob-row">
            <div className="ob-bar bid-bar" style={{ width: `${(b.size / maxSize) * 100}%` }} />
            <span className="ob-price">{(b.price * 100).toFixed(1)}¢</span>
            <span className="ob-size">{b.size.toFixed(0)}</span>
          </div>
        ))}
        {bids.length === 0 && <div className="ob-empty">No bids</div>}
      </div>
      <div className="ob-side ob-asks">
        <div className="ob-label">ASKS</div>
        {asks.map((a, i) => (
          <div key={i} className="ob-row">
            <div className="ob-bar ask-bar" style={{ width: `${(a.size / maxSize) * 100}%` }} />
            <span className="ob-price">{(a.price * 100).toFixed(1)}¢</span>
            <span className="ob-size">{a.size.toFixed(0)}</span>
          </div>
        ))}
        {asks.length === 0 && <div className="ob-empty">No asks</div>}
      </div>
    </div>
  )
}
