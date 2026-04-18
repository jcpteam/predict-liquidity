import React, { useState, useEffect } from 'react'
import { fetchSportsAllMarkets } from '../api'

const PLATFORMS = ['btx', 'polymarket', 'kalshi', 'betfair']

/**
 * 通用运动市场概览组件（板球等非足球模块使用）
 * 根据 /api/all_market 返回的数据展示 4 个平台的市场卡片
 */
export default function SportsMarketOverview({ eventData, displayName, onSelectMarket }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!eventData) return
    setLoading(true)
    fetchSportsAllMarkets(eventData)
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [eventData])

  if (loading) return <div className="detail-page"><p className="empty">Loading markets...</p></div>
  if (!data) return <div className="detail-page"><p className="empty">No data</p></div>

  // 按平台分组数据
  const platformData = {}
  data.forEach(item => {
    const platform = item.platform?.replace('market_', '')
    if (!platform || !item.markets?.length) return
    if (!platformData[platform]) platformData[platform] = []
    platformData[platform].push(...item.markets)
  })

  // 按 market_type 分组所有平台的数据，用于对齐显示
  const allMarketTypes = new Set()
  PLATFORMS.forEach(p => {
    (platformData[p] || []).forEach(m => allMarketTypes.add(m.market_type))
  })

  // 排序：Match Odds 放最前面，Completed Match 第二，Tied Match 第三，数字开头的放最后
  const sortedMarketTypes = Array.from(allMarketTypes).sort((a, b) => {
    // Match Odds 永远排第一
    if (a === 'Match Odds') return -1
    if (b === 'Match Odds') return 1
    // Completed Match 排第二
    if (a === 'Completed Match') return -1
    if (b === 'Completed Match') return 1
    // Tied Match 排第三
    if (a === 'Tied Match') return -1
    if (b === 'Tied Match') return 1
    // 数字开头的 type 放最后
    const aStartsWithDigit = /^\d/.test(a)
    const bStartsWithDigit = /^\d/.test(b)
    if (aStartsWithDigit && !bStartsWithDigit) return 1
    if (!aStartsWithDigit && bStartsWithDigit) return -1
    // 其他按字母顺序
    return a.localeCompare(b)
  })

  return (
    <div className="detail-page mkt-dashboard">
      <div className="detail-title-bar">
        <h2>{displayName || eventData?.display_name}</h2>
        {eventData?.start_time && (
          <span className="detail-time">🕐 {new Date(eventData.start_time).toLocaleString()}</span>
        )}
      </div>

      <div className="mkt-platform-header-row" style={{ gridAutoFlow: "column", gridAutoColumns: "1fr" }}>
        {PLATFORMS.map(p => (
          <div key={p} className="mkt-platform-head">
            <span className="mkt-platform-name">{p.toUpperCase()}</span>
            <span className="mkt-platform-count">: {(platformData[p] || []).length}</span>
          </div>
        ))}
      </div>

      <div className="mkt-columns-grid" style={{ gridAutoFlow: "column", gridAutoColumns: "1fr" }}>
        {PLATFORMS.map(platform => (
          <SportsPlatformColumn
            key={platform}
            platform={platform}
            markets={platformData[platform] || []}
            sortedMarketTypes={sortedMarketTypes}
            onSelectMarket={onSelectMarket}
          />
        ))}
      </div>
    </div>
  )
}

function SportsPlatformColumn({ platform, markets, sortedMarketTypes, onSelectMarket }) {
  if (!markets.length && !sortedMarketTypes.length) {
    return <div className="mkt-column"><div className="mkt-column-empty">No markets</div></div>
  }

  return (
    <div className="mkt-column">
      {sortedMarketTypes.map(marketType => {
        const market = markets.find(m => m.market_type === marketType)
        if (!market) return null
        return (
          <div key={marketType} className="mkt-col-cat">
            <div className="mkt-col-cat-title">{market.market_type}</div>
            <div className="mkt-col-subcard">
              <button
                type="button"
                className="mkt-col-subtitle"
                onClick={() => onSelectMarket?.(market.market_type, market.market_id, platform)}
              >
                {market.market_type}
              </button>
              {market.outcomes?.map((outcome, oIdx) => (
                <div key={oIdx} className="mkt-col-outcome-line">
                  <span className="mkt-col-outcome-lbl">{outcome.name}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
