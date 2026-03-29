import React, { useState, useEffect } from 'react'
import { fetchLeagues, fetchLeagueEvents, syncEvents, fetchMarkets, autoMatchAll } from './api'
import HomePage from './components/HomePage.jsx'
import LeagueSidebar from './components/LeagueSidebar.jsx'
import EventDashboard from './components/EventDashboard.jsx'
import EventDetail from './components/EventDetail.jsx'
import './style.css'

// Views: 'home' | 'leagues' | 'detail'
export default function App() {
  const [view, setView] = useState('home')
  const [leagues, setLeagues] = useState([])
  const [events, setEvents] = useState([])
  const [markets, setMarkets] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadingEvents, setLoadingEvents] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [matching, setMatching] = useState(false)
  const [matchResult, setMatchResult] = useState(null)
  const [selectedLeague, setSelectedLeague] = useState(null)
  const [selectedEventId, setSelectedEventId] = useState(null)

  const loadLeagues = async () => {
    setLoading(true)
    try {
      const [lgs, mkts] = await Promise.all([fetchLeagues(), fetchMarkets()])
      setLeagues(lgs)
      setMarkets(mkts.markets || [])
      return lgs
    } finally { setLoading(false) }
  }

  const loadEventsForLeague = async (league) => {
    setLoadingEvents(true)
    try {
      setEvents(await fetchLeagueEvents(league))
    } finally { setLoadingEvents(false) }
  }

  const handleSelectSport = (sportId) => {
    if (sportId === 'football') {
      setView('leagues')
      loadLeagues().then(lgs => {
        if (lgs.length > 0 && !selectedLeague) {
          setSelectedLeague(lgs[0].name)
          loadEventsForLeague(lgs[0].name)
        }
      })
    }
  }

  const handleSelectLeague = (league) => {
    setSelectedLeague(league)
    loadEventsForLeague(league)
  }

  const handleSelectEvent = (eventId) => {
    setSelectedEventId(eventId)
    setView('detail')
  }

  const handleBack = () => {
    if (view === 'detail') {
      setSelectedEventId(null)
      setView('leagues')
    } else {
      setView('home')
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await syncEvents()
      setMatchResult(res.auto_match ? { results: res.auto_match } : null)
      const lgs = await loadLeagues()
      if (selectedLeague) loadEventsForLeague(selectedLeague)
      else if (lgs.length > 0) {
        setSelectedLeague(lgs[0].name)
        loadEventsForLeague(lgs[0].name)
      }
    } finally { setSyncing(false) }
  }

  const handleAutoMatch = async () => {
    setMatching(true)
    setMatchResult(null)
    try {
      const res = await autoMatchAll()
      setMatchResult(res)
      if (selectedLeague) loadEventsForLeague(selectedLeague)
    } finally { setMatching(false) }
  }

  const leagueEntries = leagues.map(l => [l.name, { length: l.count }])
  const totalCount = leagues.reduce((s, l) => s + l.count, 0)

  // ── Home page ──
  if (view === 'home') {
    return (
      <div className="app">
        <header>
          <h1>⚡ Prediction Market Liquidity</h1>
        </header>
        <HomePage onSelectSport={handleSelectSport} />
      </div>
    )
  }

  // ── Detail page ──
  if (view === 'detail' && selectedEventId) {
    return (
      <div className="app">
        <header>
          <h1>⚡ Prediction Market Liquidity</h1>
          <button className="sync-btn back-btn" onClick={handleBack}>← Back to Events</button>
        </header>
        <div className="detail-fullpage">
          <EventDetail
            unifiedId={selectedEventId}
            markets={markets}
            onMappingChange={() => { if (selectedLeague) loadEventsForLeague(selectedLeague) }}
          />
        </div>
      </div>
    )
  }

  // ── Leagues + Events page ──
  return (
    <div className="app">
      <header>
        <h1>⚡ Prediction Market Liquidity</h1>
        <button className="sync-btn back-btn" onClick={handleBack}>← Home</button>
        <button className="sync-btn" onClick={handleSync} disabled={syncing}>
          {syncing ? '⏳ Syncing...' : '🔄 Refresh'}
        </button>
        <button className="sync-btn auto-match-btn" onClick={handleAutoMatch} disabled={matching}>
          {matching ? '⏳ Matching...' : '🤖 Auto-Match'}
        </button>
      </header>

      {matchResult && (
        <div className="match-result-banner">
          {matchResult.results?.map((r, i) => (
            <span key={i}>{r.market}: {r.matched} matched</span>
          ))}
          <button className="btn-sm" onClick={() => setMatchResult(null)}>✕</button>
        </div>
      )}

      <div className="main-layout">
        <LeagueSidebar
          leagues={leagueEntries}
          activeLeague={selectedLeague}
          onSelect={handleSelectLeague}
          totalCount={totalCount}
        />
        <EventDashboard
          league={selectedLeague}
          events={events}
          loading={loading || loadingEvents}
          onSelectEvent={handleSelectEvent}
        />
      </div>
    </div>
  )
}
