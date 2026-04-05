import React, { useState } from 'react'

function isLive(eventTime) {
  if (!eventTime) return false
  const start = new Date(eventTime)
  const now = new Date()
  // Match started (past start time) and within 3 hours (football ~2h + buffer)
  return now >= start && (now - start) < 3 * 60 * 60 * 1000
}

function parseTeams(title) {
  // "Team A vs. Team B" or "Team A vs Team B" or "Team A v Team B"
  const parts = title.split(/\s+(?:vs\.?|v\.?|@)\s+/i)
  if (parts.length === 2) {
    // Strip suffixes like " - More Markets"
    const clean = s => s.replace(/\s*-\s*(More Markets|Winner).*$/i, '').trim()
    return [clean(parts[0]), clean(parts[1])]
  }
  return null
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
      + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch { return dateStr }
}

export default function EventDashboard({ league, events, loading, onSelectEvent }) {
  const [filter, setFilter] = useState('')

  const filtered = filter
    ? events.filter(e => e.display_name.toLowerCase().includes(filter.toLowerCase()))
    : events

  if (!league) {
    return <main className="dashboard"><p className="empty">Select a league from the sidebar.</p></main>
  }

  return (
    <main className="dashboard">
      <div className="dashboard-header">
        <h2>{league}</h2>
        <span className="dashboard-count">{events.length} events</span>
        <input
          placeholder="Filter events..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="filter-input dash-filter"
        />
      </div>
      {loading && <p className="empty">Loading events...</p>}
      <div className="match-grid">
        {filtered.map(ev => {
          const teams = parseTeams(ev.display_name)
          return (
            <div
              key={ev.unified_id}
              className="match-card"
              onClick={() => onSelectEvent(ev.unified_id)}
              role="button"
              tabIndex={0}
              onKeyDown={e => e.key === 'Enter' && onSelectEvent(ev.unified_id)}
            >
              {ev.image && <img src={ev.image} alt="" className="match-card-img" />}
              <div className="match-card-body">
                {teams ? (
                  <div className="match-teams">
                    <span className="team-name">{teams[0]}</span>
                    <span className="vs-label">vs</span>
                    <span className="team-name">{teams[1]}</span>
                  </div>
                ) : (
                  <div className="match-title">{ev.display_name}</div>
                )}
                <div className="match-info-row">
                  {ev.end_date && <span className="match-time">🕐 {formatDate(ev.end_date)}</span>}
                </div>
                <div className="match-info-row">
                  {ev.btx_market_count > 1 && <span className="match-stat">{ev.btx_market_count} BTX markets</span>}
                  {ev.market_count != null && <span className="match-stat">{ev.market_count} markets</span>}
                  {ev.liquidity != null && <span className="match-stat">Liq: ${Number(ev.liquidity).toLocaleString()}</span>}
                  {ev.volume_24hr != null && <span className="match-stat">24h: ${Number(ev.volume_24hr).toLocaleString()}</span>}
                </div>
                <div className="match-badges">
                  {ev.is_active === false && <span className="market-badge-sm" style={{background:'#da363333',color:'#f85149'}}>ENDED</span>}
                  {isLive(ev.event_time) && <span className="market-badge-sm badge-live">● LIVE</span>}
                  {ev.linked_markets.map(m => (
                    <span key={m} className="market-badge-sm">{m}</span>
                  ))}
                </div>
              </div>
            </div>
          )
        })}
      </div>
      {!loading && filtered.length === 0 && <p className="empty">No events in this league.</p>}
    </main>
  )
}
