import React, { useState, useEffect } from 'react'
import { fetchAllMarkets } from '../api'

const PLATFORMS = ['btx', 'polymarket', 'kalshi', 'betfair']
const PLATFORM_CURRENCY = {
  btx: { symbol: '$', code: 'USD' },
  polymarket: { symbol: '', code: 'USDC' },
  kalshi: { symbol: '$', code: 'USD' },
  betfair: { symbol: '£', code: 'GBP' },
}
// Platforms that use decimal odds natively (show raw odds, not probability)
const ODDS_PLATFORMS = new Set(['btx', 'betfair'])
const GBP_TO_USD = 1.27

function toUSD(amount, platform) {
  return platform === 'betfair' ? amount * GBP_TO_USD : amount
}
function formatAmt(amount, platform, showUSD) {
  if (showUSD) return `$${toUSD(amount, platform).toFixed(0)}`
  const c = PLATFORM_CURRENCY[platform]
  return `${c.symbol}${amount.toFixed(0)} ${c.code}`
}
// Format price: odds platforms show decimal odds, others show probability ¢
function formatPrice(prob, platform) {
  if (prob == null) return '—'
  if (ODDS_PLATFORMS.has(platform) && prob > 0) {
    const odds = (1 / prob).toFixed(2)
    return odds
  }
  return `${(prob * 100).toFixed(1)}¢`
}
function isDraw(label) {
  if (!label) return false
  const l = label.toLowerCase().trim()
  return l === 'draw' || l === 'the draw' || l === 'tie' || l.startsWith('draw (')
}
function getLabel(ev, platform) {
  return platform === 'polymarket' ? (ev.event_title || ev.outcome || '') : (ev.outcome || ev.event_title || '')
}
function normLabel(s) {
  return (s || '').toLowerCase().replace(/\b(fc|afc|sc|ac|cf)\b/gi, '').trim().replace(/\s+/g, ' ')
}
function findMatch(btxLabel, btxIsDraw, events, platform) {
  if (!events || !Array.isArray(events)) return null
  for (const ev of events) {
    const l = getLabel(ev, platform)
    if (btxIsDraw && isDraw(l)) return ev
    if (!btxIsDraw && !isDraw(l)) {
      const a = normLabel(btxLabel), b = normLabel(l)
      if (a === b || a.includes(b) || b.includes(a)) return ev
    }
  }
  return null
}
function getDepth(ev) {
  if (!ev?.order_book) return 0
  return (ev.order_book.bids || []).reduce((s, b) => s + b.size, 0) +
         (ev.order_book.asks || []).reduce((s, a) => s + a.size, 0)
}
function getBestBid(ev) {
  return ev?.order_book?.bids?.[0]?.price ?? null
}
function getBestAsk(ev) {
  return ev?.order_book?.asks?.[0]?.price ?? null
}

// Tooltip wrapper
function Tip({ text, children }) {
  return <span className="tip-wrap" title={text}>{children}</span>
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
  const betfairPerBtx = data.betfair_per_btx || {}

  const grouped = {}
  for (const m of btxMarkets) {
    const key = m.market_type || 'UNKNOWN'
    if (!grouped[key]) grouped[key] = { display: m.market_type_display, markets: [] }
    grouped[key].markets.push(m)
  }

  return (
    <div className="detail-page">
      <div className="detail-title-bar">
        <h2>{displayName || data.display_name}</h2>
        <div className="detail-title-meta">
          {data.event_time && <span className="detail-time">🕐 {new Date(data.event_time).toLocaleString()}</span>}
          <button className={`currency-toggle ${showUSD ? 'active' : ''}`} onClick={() => setShowUSD(!showUSD)}>
            {showUSD ? '$ All USD' : '🔄 Convert to USD'}
          </button>
        </div>
      </div>
      {Object.entries(grouped).map(([typeKey, group]) => (
        <MarketTypeGroup key={typeKey} typeDisplay={group.display} btxMarkets={group.markets}
          otherMarkets={otherMarkets} betfairPerBtx={betfairPerBtx}
          onSelectMarket={onSelectMarket} showUSD={showUSD} />
      ))}
    </div>
  )
}

function MarketTypeGroup({ typeDisplay, btxMarkets, otherMarkets, betfairPerBtx, onSelectMarket, showUSD }) {
  return (
    <div className="mkt-section">
      <div className="mkt-section-header">
        <span className="mkt-type-name">{typeDisplay}</span>
        <span className="mkt-type-count">{btxMarkets.length} market{btxMarkets.length > 1 ? 's' : ''}</span>
      </div>
      <div className="mkt-table-wrap">
        <table className="mkt-table">
          <thead>
            <tr>
              <th className="mkt-th-outcome">Market</th>
              {PLATFORMS.map(p => (
                <th key={p} className="mkt-th-platform">
                  {p.toUpperCase()}
                  <span className="mkt-th-currency">
                    {showUSD ? 'USD' : PLATFORM_CURRENCY[p].code}
                    {ODDS_PLATFORMS.has(p) ? ' (odds)' : ' (prob)'}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {btxMarkets.map(btxMkt => (
              <MarketRow key={btxMkt.market_id} btxMkt={btxMkt} otherMarkets={otherMarkets}
                betfairEvents={betfairPerBtx[btxMkt.market_id] || null}
                onSelectMarket={onSelectMarket} showUSD={showUSD} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MarketRow({ btxMkt, otherMarkets, betfairEvents, onSelectMarket, showUSD }) {
  const outcomes = btxMkt.outcomes || []
  const marketLabel = btxMkt.display_name || btxMkt.market_type_display

  const rows = outcomes.map((btxEv, idx) => {
    const btxLabel = btxEv.outcome || ''
    const btxIsDraw = isDraw(btxLabel)
    return { btxEv, btxLabel, btxIsDraw, displayLabel: btxIsDraw ? 'Draw' : btxLabel, idx }
  })

  // Compute per-platform liquidity and spread for this market
  const platformStats = {}
  for (const p of PLATFORMS) {
    let evts
    if (p === 'btx') evts = outcomes
    else if (p === 'betfair' && betfairEvents) evts = betfairEvents
    else evts = otherMarkets[p]
    if (!evts || !Array.isArray(evts)) { platformStats[p] = { liq: 0, spread: null }; continue }

    let liq = 0, bidSum = 0, bidCount = 0
    for (const ev of evts) {
      liq += getDepth(ev)
      const bid = getBestBid(ev)
      if (bid != null) { bidSum += bid; bidCount++ }
    }
    platformStats[p] = { liq, spread: bidCount > 0 ? bidSum : null }
  }

  return (
    <>
      <tr className="mkt-row mkt-row-market-header">
        <td colSpan={PLATFORMS.length + 1} className="mkt-td-market-name">
          <span className="mkt-market-label" onClick={() => onSelectMarket(btxMkt.market_type)}>
            {marketLabel}
          </span>
        </td>
      </tr>
      {rows.map(({ btxEv, btxLabel, btxIsDraw, displayLabel, idx }) => (
        <tr key={idx} className="mkt-row">
          <td className="mkt-td-outcome">{displayLabel}</td>
          {PLATFORMS.map(p => {
            if (p === 'btx') return <Cell key={p} ev={btxEv} platform={p} showUSD={showUSD} onClick={() => onSelectMarket(btxMkt.market_type)} />
            const evts = (p === 'betfair' && betfairEvents) ? betfairEvents : otherMarkets[p]
            const matched = findMatch(btxLabel, btxIsDraw, evts, p)
            if (!matched) return <td key={p} className="mkt-td-cell mkt-td-empty">—</td>
            return <Cell key={p} ev={matched} platform={p} showUSD={showUSD} onClick={() => onSelectMarket(btxMkt.market_type)} />
          })}
        </tr>
      ))}
      {/* Market-level Liquidity + Spread row */}
      <tr className="mkt-row mkt-row-stats">
        <td className="mkt-td-outcome mkt-td-stats-label">
          <Tip text="Liquidity = Σ(bid sizes + ask sizes) for all outcomes. Overround = Σ(best bid probability) across all outcomes; fair market = 100¢, >100¢ = house edge.">
            Liquidity / Overround ⓘ
          </Tip>
        </td>
        {PLATFORMS.map(p => {
          const st = platformStats[p]
          const isOdds = ODDS_PLATFORMS.has(p)
          const isBf = p === 'betfair'
          const rawLiq = st.liq
          const usdLiq = toUSD(rawLiq, p)
          return (
            <td key={p} className="mkt-td-cell mkt-td-stats">
              <Tip text={`Liquidity = Σ(all bid sizes + ask sizes) across all outcomes in ${p.toUpperCase()}.${isBf ? ' GBP→USD: amount × ' + GBP_TO_USD : ''}`}>
                <div className="mkt-stat-liq">
                  {formatAmt(rawLiq, p, false)}
                  {isBf && <span className="mkt-cell-conv"> (${usdLiq.toFixed(0)} USD)</span>}
                </div>
              </Tip>
              <Tip text={`Overround = Σ best_bid(each outcome) as probability.${isOdds ? ' For odds: prob = 1/odds, then Σ(prob)×100.' : ''} Fair market = 100¢. >100¢ = overround (house edge).`}>
                <div className="mkt-stat-spread">
                  Overround: {st.spread != null ? `${(st.spread * 100).toFixed(1)}¢` : '—'}
                </div>
              </Tip>
            </td>
          )
        })}
      </tr>
    </>
  )
}

function Cell({ ev, platform, showUSD, onClick }) {
  const bid = getBestBid(ev)
  const ask = getBestAsk(ev)
  const isOdds = ODDS_PLATFORMS.has(platform)
  const isBf = platform === 'betfair'

  // Per-outcome liquidity = bid sizes + ask sizes
  const bidDepth = ev?.order_book?.bids?.reduce((s, b) => s + b.size, 0) || 0
  const askDepth = ev?.order_book?.asks?.reduce((s, a) => s + a.size, 0) || 0
  const liq = bidDepth + askDepth
  const usdLiq = toUSD(liq, platform)

  // Per-outcome spread = ask - bid (in probability)
  const spread = (bid != null && ask != null) ? ask - bid : null

  return (
    <td className="mkt-td-cell mkt-td-data" onClick={onClick} role="button" tabIndex={0}>
      <Tip text={`Best Bid: highest buy price.${isOdds ? ' Decimal odds (lower = more likely)' : ' Probability ¢ (higher = more likely)'}`}>
        <div className="mkt-cell-bid">Bid: {formatPrice(bid, platform)}</div>
      </Tip>
      <Tip text={`Best Ask: lowest sell price.${isOdds ? ' Decimal odds' : ' Probability ¢'}`}>
        <div className="mkt-cell-ask">Ask: {formatPrice(ask, platform)}</div>
      </Tip>
      <Tip text={`Liquidity = Σ bid sizes + Σ ask sizes for this outcome.${isBf ? ' £' + liq.toFixed(0) + ' GBP × ' + GBP_TO_USD + ' = $' + usdLiq.toFixed(0) + ' USD' : ''}`}>
        <div className="mkt-cell-liq-detail">
          Liquidity: {formatAmt(liq, platform, false)}
          {isBf && <span className="mkt-cell-conv"> (${usdLiq.toFixed(0)})</span>}
        </div>
      </Tip>
      <Tip text={`Bid-Ask Spread = Best Ask − Best Bid for this outcome. Smaller = tighter, more liquid market.`}>
        <div className="mkt-cell-spread-detail">
          Bid-Ask Spread: {spread != null ? `${(Math.abs(spread) * 100).toFixed(1)}¢` : '—'}
        </div>
      </Tip>
    </td>
  )
}
