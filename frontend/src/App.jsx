import React, { useState, useEffect } from 'react'
import { fetchLeagues, fetchLeagueEvents, syncEvents, fetchMarkets, autoMatchAll } from './api'
import LeagueSidebar from './components/LeagueSidebar.jsx'
import EventDashboard from './components/EventDashboard.jsx'
import EventDetail from './components/EventDetail.jsx'
import './style.css'

export default function App() {
  const [leagues, setLeagues] = useState([])
  const [events, setEvents] = useState([])
  const [markets, setMarkets] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadingEvents, setLoadingEvents] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [matching, setMatching] = useState(false)
  const [matchResult, setMatchResult] = useState(null)
  const [selectedLeague, setSelectedLeague] = useState(null)
  const [selectedEventId, setSelectedEventId] = useState(null)

  // 加载联赛列表和市场列表（从数据库）
  const loadLeagues = async () => {
    setLoading(true)
    try {
      const [lgs, mkts] = await Promise.all([fetchLeagues(), fetchMarkets()])
      setLeagues(lgs)
      setMarkets(mkts.markets || [])
      return lgs
    } finally { setLoading(false) }
  }

  useEffect(() => {
    loadLeagues().then(lgs => {
      if (lgs.length > 0 && !selectedLeague) {
        const first = lgs[0].name
        setSelectedLeague(first)
        loadEventsForLeague(first)
      }
    })
  }, [])

  // 加载某个联赛的事件（从数据库）
  const loadEventsForLeague = async (league) => {
    setLoadingEvents(true)
    try {
      const evts = await fetchLeagueEvents(league)
      setEvents(evts)
    } finally { setLoadingEvents(false) }
  }

  const handleSelectLeague = (league) => {
    setSelectedLeague(league)
    loadEventsForLeague(league)
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

  // 联赛列表格式转换给 LeagueSidebar
  const leagueEntries = leagues.map(l => [l.name, { length: l.count }])
  const totalCount = leagues.reduce((s, l) => s + l.count, 0)

  if (selectedEventId) {
    return (
      <div className="app">
        <header>
          <h1>⚽ Prediction Market Liquidity Comparator</h1>
          <button className="sync-btn back-btn" onClick={() => setSelectedEventId(null)}>
            ← Back to Events
          </button>
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

  return (
    <div className="app">
      <header>
        <h1>⚽ Prediction Market Liquidity Comparator</h1>
        <button className="sync-btn" onClick={handleSync} disabled={syncing}>
          {syncing ? '⏳ Syncing...' : '🔄 Refresh Events'}
        </button>
        <button className="sync-btn auto-match-btn" onClick={handleAutoMatch} disabled={matching}>
          {matching ? '⏳ Matching...' : '🤖 Auto-Match Markets'}
        </button>
      </header>

      {matchResult && (
        <div className="match-result-banner">
          {matchResult.results?.map((r, i) => (
            <span key={i}>{r.market}: {r.matched} matched / {r.total_other_events} events</span>
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
          onSelectEvent={setSelectedEventId}
        />
      </div>
    </div>
  )
}
