import React from 'react'

export default function OrderBookChart({ orderBook, showOdds = false }) {
  if (!orderBook) return null

  const bids = [...(orderBook.bids || [])].sort((a, b) => b.price - a.price)
  const asks = [...(orderBook.asks || [])].sort((a, b) => b.price - a.price)
  const bestBid = bids.length ? bids[0].price : null
  const bestAsk = asks.length ? asks[asks.length - 1].price : null
  const lastPrice = orderBook.last_price != null ? orderBook.last_price : null

  const formatPriceCents = (value, decimals = 1) => {
    const factor = 10 ** decimals
    return `${(Math.floor(value * factor) / factor).toFixed(decimals)}¢`
  }

  const formatPrice = (price) => {
    if (showOdds) {
      return price > 0 ? (1 / price).toFixed(2) : '—'
    }
    return formatPriceCents(price * 100, 1)
  }

  const formatNumber = (num, decimals = 2) => {
    return parseFloat(num.toFixed(decimals)).toLocaleString('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals
    })
  }

  const formatTotal = entry => {
    if (!entry) return ''
    return `$${formatNumber(entry.size * entry.price, 2)}`
  }

  return (
    <div className="order-book">
      <div className="ob-table-header">
        <span>PRICE</span>
        <span>SHARES</span>
        <span>TOTAL</span>
      </div>

      <div className="ob-section ob-asks">
        {asks.length > 0 ? asks.map((a, i) => (
          <div key={i} className="ob-row ask-row">
            <span className="ob-price">{formatPrice(a.price)}</span>
            <span className="ob-size">{formatNumber(a.size, 2)}</span>
            <span className="ob-total">{formatTotal(a)}</span>
          </div>
        )) : <div className="ob-empty">No asks</div>}
      </div>

      <div className="ob-section ob-bids">
        {bids.length > 0 ? bids.map((b, i) => (
          <div key={i} className="ob-row bid-row">
            <span className="ob-price">{formatPrice(b.price)}</span>
            <span className="ob-size">{formatNumber(b.size, 2)}</span>
            <span className="ob-total">{formatTotal(b)}</span>
          </div>
        )) : <div className="ob-empty">No bids</div>}
      </div>
    </div>
  )
}
