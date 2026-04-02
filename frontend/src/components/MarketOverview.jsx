import React, { useState, useEffect } from 'react'
import { fetchAllMarkets } from '../api'

const PLATFORMS = ['btx', 'polymarket', 'kalshi', 'betfair']

// Native currency per platform
const PLATFORM_CURRENCY = {
  btx: { symbol: '$', code: 'USD' },
  polymarket: { symbol: '', code: 'USDC' },
  kalshi: { symbol: '$', code: 'USD' },
  betfair: { symbol: '£', code: 'GBP' },
}

// GBP → USD rate (approximate, could be fetched from API)
const GBP_TO_USD = 1.27

function toUSD(amount, platform) {
  if (platform === 'betfair') return amount * GBP_TO_USD
  return amount // USD and USDC ≈ 1:1
}

function formatAmount(amount, platform, showUSD) {
  if (showUSD) {
    const usd = toUSD(amount, platform)
    return `$${usd.toFixed(0)}`
  }
  const cur = PLATFORM_CURRENCY[platform] || { symbol: '$', code: '' }
  return `${cur.symbol}${amount.toFixed(0)} ${cur.code}`
}

function getTotalDepth(events) {
  if (!events || !Array.isArray(events)) return 0
  let d = 0
  for (const ev of events) {
    if (ev.order_book) {
      for (const b of (ev.order_book.bids || [])) d += b.size
      for (const a of (ev.order_book.asks || [])) d += a.size
    }
  }
  return d
}

function isDraw(label) {
  if (!label) return false
  const l = label.toLowerCase().trim()
  return l === 'draw' || l === 'the draw' || l === 'tie' || l.startsWith('draw (')
}

function getLabel(ev, platform) {
  if (platform === 'polymarket') return ev.event_title || ev.outcome || ''
  return ev.outcome || ev.event_title || ''
}

function normLabel(s) {
  return (s || '').toLowerCase().replace(/\b(fc|afc|sc|ac|cf)\b/gi, '').trim().replace(/\s+/g, ' ')
}

export default function MarketOverview({ unifiedId, displayName, onSelectMarket }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showUSD, setShowUSD] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchAllMarkets(unifiedId).then(d => { setData(d); setLoading(false) }).catch(() => setLoading(false))
  }, [unifiedId])

  if (loading) return <div className="detail-page"><p className="empty">Loading markets...</p></div>
  if (!data) return <div className="detail-page"><p className="empty">No data</p></div>

  const btxMarkets = data.btx_markets || []
  const otherMarkets = data.other_markets || {}

  return (
    <div className="detail-page">
      <div className="detail-title-bar">
        <h2>{displayName || data.display_name}</h2>
        <div className="detail-title-meta">
          {data.event_time && <span className="detail-time">🕐 {new Date(data.event_time).toLocaleString()}</span>}
          <button className={`currency-toggle ${showUSD ? 'active' : ''}`} onClick={() => setShowUSD(!showUSD)}>
            {showUSD ? '$ USD' : '🔄 Convert to USD'}
          </button>
        </div>
      </div>

      {btxMarkets.length > 0 ? (
        btxMarkets.map(btxMkt => (
          <MarketTypeSection
            key={btxMkt.market_id}
            btxMkt={btxMkt}
            otherMarkets={otherMarkets}
            onSelectMarket={onSelectMarket}
            showUSD={showUSD}
          />
        ))
      ) : (
        <p className="empty">No BTX markets found</p>
      )}
    </div>
  )
}

function MarketTypeSection({ btxMkt, otherMarkets, onSelectMarket, showUSD }) {
  const btxOutcomes = btxMkt.outcomes || []
  const btxLiq = btxMkt.liquidity || 0

  const otherLiqs = {}
  for (const p of PLATFORMS) {
    if (p === 'btx') continue
    otherLiqs[p] = getTotalDepth(otherMarkets[p])
  }

  return (
    <div className="mkt-section">
      <div className="mkt-section-header">
        <span className="mkt-type-name">{btxMkt.market_type_display}</span>
        <span className="mkt-type-id">{btxMkt.market_id}</span>
      </div>
      <div className="mkt-table-wrap">
        <table className="mkt-table">
          <thead>
            <tr>
              <th className="mkt-th-outcome">Outcome</th>
              {PLATFORMS.map(p => (
                <th key={p} className="mkt-th-platform">
                  {p.toUpperCase()}
                  <span className="mkt-th-currency">{showUSD ? 'USD' : PLATFORM_CURRENCY[p].code}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {btxOutcomes.map((btxEv, idx) => {
              const btxLabel = btxEv.outcome || ''
              const btxIsDraw = isDraw(btxLabel)
              const displayLabel = btxIsDraw ? 'Draw' : btxLabel
              return (
                <tr key={idx} className="mkt-row">
                  <td className="mkt-td-outcome">{displayLabel}</td>
                  {PLATFORMS.map(p => {
                    if (p === 'btx') {
                      return <MarketCell key={p} ev={btxEv} platform={p} showUSD={showUSD}
                               onClick={() => onSelectMarket(btxMkt.market_type)} />
                    }
                    const events = otherMarkets[p]
                    if (!events || !Array.isArray(events)) return <td key={p} className="mkt-td-cell mkt-td-empty">—</td>
                    const matched = findMatchingOutcome(btxLabel, btxIsDraw, events, p)
                    if (!matched) return <td key={p} className="mkt-td-cell mkt-td-empty">—</td>
                    return <MarketCell key={p} ev={matched} platform={p} showUSD={showUSD}
                             onClick={() => onSelectMarket(btxMkt.market_type)} />
                  })}
                </tr>
              )
            })}
            <tr className="mkt-row mkt-row-summary">
              <td className="mkt-td-outcome mkt-td-summary-label"
                  title="Liquidity = Sum of all bid sizes + ask sizes across all outcomes">
                Liquidity 💡
              </td>
              {PLATFORMS.map(p => {
                const liq = p === 'btx' ? btxLiq : (otherLiqs[p] || 0)
                return (
                  <td key={p} className="mkt-td-cell mkt-td-summary">
                    <span className="mkt-cell-liq">{formatAmount(liq, p, showUSD)}</span>
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

function findMatchingOutcome(btxLabel, btxIsDraw, events, platform) {
  for (const ev of events) {
    const evLabel = getLabel(ev, platform)
    const evIsDraw = isDraw(evLabel)
    if (btxIsDraw && evIsDraw) return ev
    if (!btxIsDraw && !evIsDraw) {
      const a = normLabel(btxLabel)
      const b = normLabel(evLabel)
      if (a === b || a.includes(b) || b.includes(a)) return ev
    }
  }
  return null
}

function MarketCell({ ev, platform, showUSD, onClick }) {
  const bid = ev.order_book?.bids?.[0]?.price
  const ask = ev.order_book?.asks?.[0]?.price
  const rawDepth = ev.order_book
    ? (ev.order_book.bids || []).reduce((s, b) => s + b.size, 0) + (ev.order_book.asks || []).reduce((s, a) => s + a.size, 0)
    : 0
  return (
    <td className="mkt-td-cell mkt-td-data" onClick={onClick} role="button" tabIndex={0}>
      <div className="mkt-cell-bid">Bid: {bid != null ? `${(bid*100).toFixed(1)}¢` : '—'}</div>
      <div className="mkt-cell-ask">Ask: {ask != null ? `${(ask*100).toFixed(1)}¢` : '—'}</div>
      <div className="mkt-cell-depth">{formatAmount(rawDepth, platform, showUSD)}</div>
    </td>
  )
}
