import React, { useState } from 'react'

export default function LeagueSidebar({ leagues, activeLeague, onSelect, totalCount }) {
  const [filter, setFilter] = useState('')

  const filtered = filter
    ? leagues.filter(([name]) => name.toLowerCase().includes(filter.toLowerCase()))
    : leagues

  return (
    <aside className="league-sidebar">
      <div className="sidebar-header">
        <h2>⚽ Leagues ({totalCount})</h2>
        <input
          placeholder="Filter leagues..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="filter-input"
        />
      </div>
      <div className="league-list">
        {filtered.map(([name, evts]) => (
          <div
            key={name}
            className={`league-item ${activeLeague === name ? 'active' : ''}`}
            onClick={() => onSelect(name)}
            role="button"
            tabIndex={0}
            onKeyDown={e => e.key === 'Enter' && onSelect(name)}
          >
            <span className="league-item-name">{name}</span>
            <span className="league-item-count">{evts.length}</span>
          </div>
        ))}
        {filtered.length === 0 && <p className="empty">No leagues found.</p>}
      </div>
    </aside>
  )
}
