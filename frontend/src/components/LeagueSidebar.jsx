import React, { useState } from 'react'

export default function LeagueSidebar({ leagues, activeLeague, onSelect, totalCount }) {
  const [filter, setFilter] = useState('')

  // Polymarket-style top categories
  const categories = [
    { name: 'Sports', icon: '⚽', active: true },
    { name: 'Politics', icon: '🏛️', active: false },
    { name: 'Crypto', icon: '₿', active: false },
    { name: 'Culture', icon: '🎬', active: false },
    { name: 'Science', icon: '🔬', active: false },
  ]

  const filtered = filter
    ? leagues.filter(([name]) => name.toLowerCase().includes(filter.toLowerCase()))
    : leagues

  return (
    <aside className="league-sidebar">
      <div className="category-tabs">
        {categories.map(cat => (
          <div
            key={cat.name}
            className={`category-tab ${cat.active ? 'active' : 'disabled'}`}
            title={cat.active ? cat.name : `${cat.name} (coming soon)`}
          >
            <span className="cat-icon">{cat.icon}</span>
            <span className="cat-name">{cat.name}</span>
          </div>
        ))}
      </div>
      <div className="sidebar-header">
        <h2>Leagues ({totalCount})</h2>
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
