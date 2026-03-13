import React, { useState } from 'react'

export default function EventList({ events, loading, selectedId, onSelect }) {
  const [filter, setFilter] = useState('')

  const filtered = events.filter(e =>
    e.display_name.toLowerCase().includes(filter.toLowerCase())
  )

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
      {loading && <p className="empty">Loading events...</p>}
      <div className="event-list">
        {filtered.map(ev => (
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
        {!loading && filtered.length === 0 && <p className="empty">No events found.</p>}
      </div>
    </aside>
  )
}
