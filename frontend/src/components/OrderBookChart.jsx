import React from 'react'

export default function OrderBookChart({ orderBook, showOdds = false, marketName = '' }) {
  if (!orderBook) return null
  const isBetfair = marketName === 'betfair'

  const bids = [...(orderBook.bids || [])].sort((a, b) => b.price - a.price)
  const asks = [...(orderBook.asks || [])].sort((a, b) => b.price - a.price)

  const formatPrice = (price) => {
    if (showOdds) return price > 0 ? (1 / price).toFixed(2) : '\u2014'
    return `${(price * 100).toFixed(1)}\u00A2`
  }

  const fmt = (num) => parseFloat(num.toFixed(2)).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  })

  const formatTotal = (entry) => {
    if (!entry) return ''
    const val = entry.size * entry.price
    if (isBetfair) return `\u00A3${fmt(val)} ($${fmt(val * 1.27)})`
    return `$${fmt(val)}`
  }

  return (
    <div className="order-book">
      <div className="ob-table-header">
        <span>PRICE</span>
        <span>SHARES</span>
        <span>TOTAL {isBetfair ? '(GBP/USD)' : ''}</span>
      </div>
      <div className="scroll-box ob-section ob-asks">
        {asks.length > 0 ? asks.map((a, i) => (
          <div key={i} className="ob-row ask-row">
            <span className="ob-price">{formatPrice(a.price)}</span>
            <span className="ob-size">{fmt(a.size)}</span>
            <span className="ob-total">{formatTotal(a)}</span>
          </div>
        )) : <div className="ob-empty">No asks</div>}
      </div>
      <div className="scroll-box ob-section ob-bids">
        {bids.length > 0 ? bids.map((b, i) => (
          <div key={i} className="ob-row bid-row">
            <span className="ob-price">{formatPrice(b.price)}</span>
            <span className="ob-size">{fmt(b.size)}</span>
            <span className="ob-total">{formatTotal(b)}</span>
          </div>
        )) : <div className="ob-empty">No bids</div>}
      </div>
    </div>
  )
}
