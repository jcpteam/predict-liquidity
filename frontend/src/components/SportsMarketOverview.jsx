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
            onSelectMarket={onSelectMarket}
          />
        ))}
      </div>
    </div>
  )
}

function SportsPlatformColumn({ platform, markets, onSelectMarket }) {
  if (!markets.length) {
    return <div className="mkt-column"><div className="mkt-column-empty">No markets</div></div>
  }

  return (
    <div className="mkt-column">
      {markets.map((market, idx) => (
        <div key={idx} className="mkt-col-cat">
          <div className="mkt-col-cat-title">{market.market_type}</div>
          <div className="mkt-col-subcard">
            <button
              type="button"
              className="mkt-col-subtitle"
              onClick={() => onSelectMarket?.(market.market_type, null)}
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
      ))}
    </div>
  )
}
