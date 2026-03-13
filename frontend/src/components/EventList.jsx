import React, { useState, useMemo } from 'react'

// 通用 tag 过滤掉，只保留联赛/赛事级别的 tag 作为分类
const GENERIC_TAGS = new Set([
  'Soccer', 'Sports', 'Games', 'Goals', 'Awards', 'Culture',
  'Celebrities', 'World', 'Parlays', 'Geopolitics', 'Politics',
  'Hide From New', 'yellow card', 'red card', 'red cards',
  'assists', 'assist', 'goal', 'goal contributions', 'goals',
  'clean sheet', 'clean sheets', 'goalie', 'goalkeeper', 'keeper',
  'card', 'golden boot', 'most valuable player', 'mvp',
  'man of the match', 'player of the match', 'motm', 'potm',
  'transfer', 'sea',
])

// 联赛标签标准化映射
const TAG_NORMALIZE = {
  'Premier League': 'EPL',
  'Champions League': 'UCL',
  'Europa League': 'UEL',
  "Women's Champions League": 'UWCL',
  'UEFA Europa League': 'UEL',
  'UEFA Conference League': 'UECL',
  'Europa Conference League': 'UECL',
  'Carabao Cup': 'EFL Cup',
}

function getLeagueTag(tags) {
  if (!tags || tags.length === 0) return 'Other'
  for (const t of tags) {
    if (GENERIC_TAGS.has(t)) continue
    // 跳过队名级别的 tag（通常只出现 1-2 次，且包含空格+小写）
    if (/^[a-z]/.test(t) && !t.includes(' League') && !t.includes(' Cup')) continue
    return TAG_NORMALIZE[t] || t
  }
  return 'Other'
}

export default function EventList({ events, loading, selectedId, onSelect }) {
  const [filter, setFilter] = useState('')
  const [expandedGroups, setExpandedGroups] = useState({})

  const filtered = useMemo(() =>
    events.filter(e =>
      e.display_name.toLowerCase().includes(filter.toLowerCase())
    ),
    [events, filter]
  )

  // 按联赛分组
  const grouped = useMemo(() => {
    const groups = {}
    for (const ev of filtered) {
      const league = getLeagueTag(ev.tags)
      if (!groups[league]) groups[league] = []
      groups[league].push(ev)
    }
    // 按事件数量排序，Other 放最后
    return Object.entries(groups).sort((a, b) => {
      if (a[0] === 'Other') return 1
      if (b[0] === 'Other') return -1
      return b[1].length - a[1].length
    })
  }, [filtered])

  const toggleGroup = (league) => {
    setExpandedGroups(prev => ({ ...prev, [league]: !prev[league] }))
  }

  // 默认展开前 5 个分组
  const isExpanded = (league) => {
    if (league in expandedGroups) return expandedGroups[league]
    const idx = grouped.findIndex(([l]) => l === league)
    return idx < 5
  }

  return (
    <aside className="event-list-panel">
      <div className="list-header">
        <h2>Soccer Events ({events.length})</h2>
        <input
          placeholder="Filter events..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="filter-input"
        />
      </div>
      {loading && <p className="empty" style={{padding:'12px 16px'}}>Loading events...</p>}
      <div className="event-list">
        {grouped.map(([league, evts]) => (
          <div key={league} className="league-group">
            <div
              className="league-header"
              onClick={() => toggleGroup(league)}
              role="button"
              tabIndex={0}
              onKeyDown={e => e.key === 'Enter' && toggleGroup(league)}
            >
              <span className="league-arrow">{isExpanded(league) ? '▾' : '▸'}</span>
              <span className="league-name">{league}</span>
              <span className="league-count">{evts.length}</span>
            </div>
            {isExpanded(league) && evts.map(ev => (
              <div
                key={ev.unified_id}
                className={`event-item ${selectedId === ev.unified_id ? 'active' : ''}`}
                onClick={() => onSelect(ev.unified_id)}
              >
                <div className="event-item-main">
                  {ev.image && <img src={ev.image} alt="" className="event-thumb" />}
                  <div className="event-item-info">
                    <span className="event-title">{ev.display_name}</span>
                    <div className="event-meta-row">
                      {ev.market_count != null && <span className="meta-tag">{ev.market_count} markets</span>}
                      {ev.volume_24hr != null && <span className="meta-tag">24h: ${Number(ev.volume_24hr).toLocaleString()}</span>}
                      {ev.liquidity != null && <span className="meta-tag">Liq: ${Number(ev.liquidity).toLocaleString()}</span>}
                    </div>
                    <div className="linked-badges">
                      {ev.linked_markets.map(m => (
                        <span key={m} className="market-badge-sm">{m}</span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ))}
        {!loading && filtered.length === 0 && <p className="empty" style={{padding:'12px 16px'}}>No events found.</p>}
      </div>
    </aside>
  )
}
