import React, { useState, useEffect, useMemo } from 'react'
import { fetchAllMarkets } from '../api'

const PLATFORMS = ['btx', 'polymarket', 'kalshi', 'betfair']
const PLATFORM_CURRENCY = {
  btx: { symbol: '$', code: 'USD' },
  polymarket: { symbol: '', code: 'USDC' },
  kalshi: { symbol: '$', code: 'USD' },
  betfair: { symbol: '£', code: 'GBP' },
}
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
const MKT_ALIASES = {
  'wolves': 'wolverhampton', 'wolverhampton wanderers': 'wolverhampton',
  'spurs': 'tottenham', 'tottenham hotspur': 'tottenham',
  'man utd': 'manchester united', 'man united': 'manchester united',
  'man city': 'manchester city', 'nottm forest': 'nottingham forest',
  'nott forest': 'nottingham forest', 'west ham united': 'west ham',
  'newcastle united': 'newcastle', 'brighton and hove albion': 'brighton',
  'brighton hove albion': 'brighton', 'leicester city': 'leicester',
  'atletico de madrid': 'atletico', 'atletico madrid': 'atletico',
  'borussia dortmund': 'dortmund', 'paris saint germain': 'psg',
  'paris saint-germain': 'psg', 'inter milan': 'inter', 'internazionale': 'inter',
  'ac milan': 'milan', 'bayern munchen': 'bayern munich', 'bayern münchen': 'bayern munich',
}
function resolveAlias(name) {
  const n = normLabel(name)
  return MKT_ALIASES[n] || n
}
function findMatch(btxLabel, btxIsDraw, events, platform) {
  if (!events || !Array.isArray(events)) return null
  for (const ev of events) {
    const l = getLabel(ev, platform)
    if (btxIsDraw && isDraw(l)) return ev
    if (!btxIsDraw && !isDraw(l)) {
      const a = resolveAlias(btxLabel), b = resolveAlias(l)
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

function Tip({ text, children }) {
  return <span className="tip-wrap" title={text}>{children}</span>
}

function isLive(eventTime) {
  if (!eventTime) return false
  const start = new Date(eventTime)
  const now = new Date()
  return now >= start && (now - start) < 3 * 60 * 60 * 1000
}

/**
 * UI 的“行情数量”按每个 market label 下的 outcomes 行数来算。
 * 这里的“总数”= 所有 BTX markets 的 outcomes.length 之和。
 */
function getTotalOutcomeCount(btxMarkets) {
  return (Array.isArray(btxMarkets) ? btxMarkets : []).reduce(
    (sum, m) => sum + (Array.isArray(m?.outcomes) ? m.outcomes.length : 0),
    0,
  )
}

/**
 * 每个平台独立展示的“行情数量”。
 * - `btx`：所有 btx markets 的 outcomes.length 之和
 * - `polymarket` / `kalshi`：other_markets[平台].length
 * - `betfair`：betfair_per_btx 中可用映射市场数量
 */
function getVisibleBetfairMarketCount(btxMarkets, otherMarkets, betfairPerBtx) {
  if (!Array.isArray(btxMarkets)) return 0
  let count = 0
  for (const btxMkt of btxMarkets) {
    const betfairEvents = betfairPerBtx?.[btxMkt.market_id] || null
    const rows = buildOutcomeRows(btxMkt.outcomes)
    if (platformSubBlockHasContent('betfair', btxMkt, rows, otherMarkets, betfairEvents)) {
      count += 1
    }
  }
  return count
}

function getPerPlatformQuoteCounts(btxMarkets, otherMarkets, betfairPerBtx) {
  return {
    btx: getTotalOutcomeCount(btxMarkets),
    polymarket: Array.isArray(otherMarkets?.polymarket) ? otherMarkets.polymarket.length : 0,
    kalshi: Array.isArray(otherMarkets?.kalshi) ? otherMarkets.kalshi.length : 0,
    betfair: getVisibleBetfairMarketCount(btxMarkets, otherMarkets, betfairPerBtx),
  }
}

function buildOutcomeRows(outcomes) {
  return (outcomes || []).map((btxEv, idx) => {
    const btxLabel = btxEv.outcome || ''
    const btxIsDraw = isDraw(btxLabel)
    return { btxEv, btxLabel, btxIsDraw, displayLabel: btxIsDraw ? 'Draw' : btxLabel, idx }
  })
}

function computePlatformMarketStats(btxMkt, platform, otherMarkets, betfairEvents) {
  const outcomes = btxMkt.outcomes || []
  let evts
  if (platform === 'btx') evts = outcomes
  else if (platform === 'betfair' && betfairEvents) evts = betfairEvents
  else evts = otherMarkets[platform]
  if (!evts || !Array.isArray(evts)) return { liq: 0, spread: null }

  let liq = 0, bidSum = 0, bidCount = 0
  for (const ev of evts) {
    liq += getDepth(ev)
    const bid = getBestBid(ev)
    if (bid != null) { bidSum += bid; bidCount++ }
  }
  return { liq, spread: bidCount > 0 ? bidSum : null }
}

function platformSubBlockHasContent(platform, btxMkt, rows, otherMarkets, betfairEvents) {
  if (platform === 'btx') return true
  const isMatchOdds = btxMkt.market_type === 'FOOTBALL_FULL_TIME_MATCH_ODDS'
  if ((platform === 'polymarket' || platform === 'kalshi') && !isMatchOdds) return false

  if (platform === 'betfair') {
    if (!betfairEvents?.length) return false
    return rows.some(({ btxLabel, btxIsDraw }) =>
      findMatch(btxLabel, btxIsDraw, betfairEvents, platform))
  }

  const evts = otherMarkets[platform]
  if (!evts?.length) return false
  return rows.some(({ btxLabel, btxIsDraw }) =>
    findMatch(btxLabel, btxIsDraw, evts, platform))
}

function OutcomeCellDiv({ ev, platform, onClick }) {
  const bid = getBestBid(ev)
  const ask = getBestAsk(ev)
  const isOdds = ODDS_PLATFORMS.has(platform)
  const isBf = platform === 'betfair'
  const bidOdds = bid && bid > 0 ? (1 / bid).toFixed(2) : null
  const askOdds = ask && ask > 0 ? (1 / ask).toFixed(2) : null
  const bidDepth = ev?.order_book?.bids?.reduce((s, b) => s + b.size, 0) || 0
  const askDepth = ev?.order_book?.asks?.reduce((s, a) => s + a.size, 0) || 0
  const liq = bidDepth + askDepth
  const usdLiq = toUSD(liq, platform)
  const spreadProb = (bid != null && ask != null) ? Math.abs(ask - bid) : null
  const spreadOdds = (bidOdds && askOdds) ? (parseFloat(askOdds) - parseFloat(bidOdds)).toFixed(2) : null

  return (
    <div className="mkt-outcome-cell mkt-td-data" onClick={onClick} role="button" tabIndex={0}>
      <Tip text={isOdds ? `Best Bid (decimal odds). Lower odds = higher probability. prob = 1/odds` : `Best Bid (probability ¢)`}>
        <div className="mkt-cell-bid">
          Bid: {isOdds ? (bidOdds || '—') : (bid != null ? `${(bid * 100).toFixed(1)}¢` : '—')}
        </div>
      </Tip>
      <Tip text={isOdds ? `Best Ask (decimal odds). prob = 1/odds` : `Best Ask (probability ¢)`}>
        <div className="mkt-cell-ask">
          Ask: {isOdds ? (askOdds || '—') : (ask != null ? `${(ask * 100).toFixed(1)}¢` : '—')}
        </div>
      </Tip>
      <Tip text={`Liquidity = Σ(bid sizes) + Σ(ask sizes).${isBf ? ` £${liq.toFixed(0)} × ${GBP_TO_USD} = $${usdLiq.toFixed(0)}` : ''}`}>
        <div className="mkt-cell-liq-detail">
          Liquidity: {formatAmt(liq, platform, false)}
          {platform !== 'btx' && platform !== 'kalshi' && <span className="mkt-cell-conv"> (${usdLiq.toFixed(0)} USD)</span>}
        </div>
      </Tip>
      <Tip text={isOdds
        ? `Bid-Ask Spread: odds diff = ${spreadOdds || '—'}, prob diff = ${spreadProb != null ? (spreadProb * 100).toFixed(1) + '¢' : '—'}. Formula: |1/ask_odds − 1/bid_odds|×100`
        : `Bid-Ask Spread = |Ask − Bid|. Smaller = tighter market.`}>
        <div className="mkt-cell-spread-detail">
          Spread: {isOdds
            ? (spreadOdds != null ? `${spreadOdds} odds` : '—')
            : (spreadProb != null ? `${(spreadProb * 100).toFixed(1)}¢` : '—')}
          {isOdds && spreadProb != null && <span className="mkt-cell-conv"> ({(spreadProb * 100).toFixed(1)}¢)</span>}
        </div>
      </Tip>
    </div>
  )
}

function MarketPlatformStatsDiv({ btxMkt, platform, otherMarkets, betfairEvents }) {
  const st = computePlatformMarketStats(btxMkt, platform, otherMarkets, betfairEvents)
  const isOdds = ODDS_PLATFORMS.has(platform)
  const isBf = platform === 'betfair'
  const rawLiq = st.liq
  const usdLiq = toUSD(rawLiq, platform)

  return (
    <div className="mkt-col-substats">
      <Tip text="Liquidity = Σ(bid sizes + ask sizes) for all outcomes. Overround = Σ(best bid probability) across all outcomes; fair market = 100¢, >100¢ = house edge.">
        <div className="mkt-col-stats-hdr">Liquidity / Overround ⓘ</div>
      </Tip>
      <Tip text={`Liquidity = Σ(all bid+ask sizes) in ${platform.toUpperCase()}.${isBf ? ` £${rawLiq.toFixed(0)} GBP × ${GBP_TO_USD} = $${usdLiq.toFixed(0)} USD` : ''}`}>
        <div className="mkt-stat-liq">
          Liquidity: {formatAmt(rawLiq, platform, false)}
          {isBf && <span className="mkt-cell-conv"> (${usdLiq.toFixed(0)} USD)</span>}
        </div>
      </Tip>
      <Tip text={`Overround = Σ best_bid(each outcome) as probability.${isOdds ? ' For odds: prob=1/odds, Σ(prob)×100.' : ''} Fair=100¢, >100¢=house edge.`}>
        <div className="mkt-stat-spread">
          Overround: {st.spread != null ? `${(st.spread * 100).toFixed(1)}¢` : '—'}
        </div>
      </Tip>
    </div>
  )
}

function PlatformColumn({ platform, grouped, otherMarkets, betfairPerBtx, onSelectMarket }) {
  const blocks = []
  for (const [typeKey, group] of Object.entries(grouped)) {
    const subBlocks = []
    for (const btxMkt of group.markets) {
      const betfairEvents = betfairPerBtx[btxMkt.market_id] || null
      const isMatchOdds = btxMkt.market_type === 'FOOTBALL_FULL_TIME_MATCH_ODDS'
      if (platform !== 'btx' && (platform === 'polymarket' || platform === 'kalshi') && !isMatchOdds) {
        continue
      }

      const marketLabel = btxMkt.display_name || btxMkt.market_type_display
      const rows = buildOutcomeRows(btxMkt.outcomes)

      if (!platformSubBlockHasContent(platform, btxMkt, rows, otherMarkets, betfairEvents)) {
        continue
      }

      subBlocks.push(
        <div key={btxMkt.market_id} className="mkt-col-subcard">
          <button type="button" className="mkt-col-subtitle" onClick={() => onSelectMarket(btxMkt.market_type)}>
            {marketLabel}
          </button>
          {rows.map(({ btxEv, btxLabel, btxIsDraw, displayLabel, idx }) => {
            let ev = null
            let emptyKind = 'empty'
            if (platform === 'btx') {
              ev = btxEv
            } else {
              const evts = platform === 'betfair' ? betfairEvents : otherMarkets[platform]
              ev = findMatch(btxLabel, btxIsDraw, evts, platform)
              if (!ev && (platform === 'polymarket' || platform === 'kalshi') && !isMatchOdds) {
                emptyKind = 'na'
              }
            }

            return (
              <div key={idx} className="mkt-col-outcome-line">
                <span className="mkt-col-outcome-lbl">{displayLabel}</span>
                {ev ? (
                  <OutcomeCellDiv ev={ev} platform={platform}
                    onClick={() => onSelectMarket(btxMkt.market_type)} />
                ) : (
                  <div className={`mkt-col-outcome-empty mkt-td-${emptyKind}`}>
                    {emptyKind === 'na' ? 'N/A' : '—'}
                  </div>
                )}
              </div>
            )
          })}
          <MarketPlatformStatsDiv btxMkt={btxMkt} platform={platform} otherMarkets={otherMarkets}
            betfairEvents={betfairEvents} />
        </div>
      )
    }
    if (subBlocks.length > 0) {
      blocks.push(
        <div key={typeKey} className="mkt-col-cat">
          <div className="mkt-col-cat-title">{group.display}</div>
          {subBlocks}
        </div>
      )
    }
  }

  return (
    <div className="mkt-column">
      {blocks.length === 0 ? (
        <div className="mkt-column-empty">No markets</div>
      ) : blocks}
    </div>
  )
}

function PlatformHeaderRow({ counts, showUSD }) {
  return (
    <div className="mkt-platform-header-row">
      {PLATFORMS.map(p => (
        <div key={p} className="mkt-platform-head">
          <div className="mkt-platform-name-line">
            <span className="mkt-platform-name">{p.toUpperCase()}</span>
            <span className="mkt-platform-count">: {counts[p]}</span>
          </div>
          <span className="mkt-th-currency mkt-platform-sub">
            {showUSD ? 'USD' : PLATFORM_CURRENCY[p].code}
            {ODDS_PLATFORMS.has(p) ? ' (ODDS)' : ' (PROB)'}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function MarketOverview({ unifiedId, displayName, onSelectMarket }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showUSD, setShowUSD] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchAllMarkets(unifiedId).then(d => { setData(d); setLoading(false) }).catch(() => setLoading(false))
  }, [unifiedId])

  const grouped = useMemo(() => {
    if (!data?.btx_markets) return {}
    const g = {}
    for (const m of data.btx_markets) {
      const key = m.market_type || 'UNKNOWN'
      if (!g[key]) g[key] = { display: m.market_type_display, markets: [] }
      g[key].markets.push(m)
    }
    return g
  }, [data])

  if (loading) return <div className="detail-page"><p className="empty">Loading markets...</p></div>
  if (!data) return <div className="detail-page"><p className="empty">No data</p></div>

  const btxMarkets = data.btx_markets || []
  const otherMarkets = data.other_markets || {}
  const betfairPerBtx = data.betfair_per_btx || {}
  const totalOutcomeCount = getTotalOutcomeCount(btxMarkets)
  const perPlatformCounts = getPerPlatformQuoteCounts(btxMarkets, otherMarkets, betfairPerBtx)
  const totalAllMarkets = totalOutcomeCount

  return (
    <div className="detail-page mkt-dashboard">
      <div className="detail-title-bar">
        <h2>{displayName || data.display_name}</h2>
        <div className="detail-title-meta">
          {data.event_time && <span className="detail-time">🕐 {new Date(data.event_time).toLocaleString()}</span>}
          {data.event_time && isLive(data.event_time) && <span className="live-dot">● LIVE</span>}
          <Tip text="Total quotes = sum of all outcomes across all market labels (e.g. Match Odds 3 + Total Goals 4 = 7).">
            <span className="mkt-all-markets-total">All markets: {totalAllMarkets}</span>
          </Tip>
          <button type="button" className={`currency-toggle ${showUSD ? 'active' : ''}`} onClick={() => setShowUSD(!showUSD)}>
            {showUSD ? '$ All USD' : '🔄 Convert to USD'}
          </button>
        </div>
      </div>

      <PlatformHeaderRow counts={perPlatformCounts} showUSD={showUSD} />

      <div className="mkt-columns-grid">
        {PLATFORMS.map(p => (
          <PlatformColumn
            key={p}
            platform={p}
            grouped={grouped}
            otherMarkets={otherMarkets}
            betfairPerBtx={betfairPerBtx}
            onSelectMarket={onSelectMarket}
          />
        ))}
      </div>
    </div>
  )
}
