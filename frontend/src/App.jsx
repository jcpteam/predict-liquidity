import React, { useState, useEffect } from 'react'
import { fetchEvents, syncEvents, fetchMarkets, autoMatchAll } from './api'
import LeagueSidebar from './components/LeagueSidebar.jsx'
import EventDashboard from './components/EventDashboard.jsx'
import EventDetail from './components/EventDetail.jsx'
import './style.css'

// 通用 tag 过滤
const GENERIC_TAGS = new Set([
  'Soccer','Sports','Games','Goals','Awards','Culture',
  'Celebrities','World','Parlays','Geopolitics','Politics',
  'Hide From New','yellow card','red card','red cards',
  'assists','assist','goal','goal contributions','goals',
  'clean sheet','clean sheets','goalie','goalkeeper','keeper',
  'card','golden boot','most valuable player','mvp',
  'man of the match','player of the match','motm','potm',
  'transfer','sea',
])
const TAG_NORMALIZE = {
  'Premier League':'EPL','Champions League':'UCL',
  'Europa League':'UEL',"Women's Champions League":'UWCL',
  'UEFA Europa League':'UEL','UEFA Conference League':'UECL',
  'Europa Conference League':'UECL','Carabao Cup':'EFL Cup',
}

function getLeagueTag(tags) {
  if (!tags || !tags.length) return 'Other'
  for (const t of tags) {
    if (GENERIC_TAGS.has(t)) continue
    if (/^[a-z]/.test(t) && !t.includes(' League') && !t.includes(' Cup')) continue
    return TAG_NORMALIZE[t] || t
  }
  return 'Other'
}

export default function App() {
  const [events, setEvents] = useState([])
  const [markets, setMarkets] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [matching, setMatching] = useState(false)
  const [matchResult, setMatchResult] = useState(null)
  const [selectedLeague, setSelectedLeague] = useState(null)
  const [selectedEventId, setSelectedEventId] = useState(null)

  const reload = async () => {
    setLoading(true)
    try {
      const [evts, mkts] = await Promise.all([fetchEvents(), fetchMarkets()])
      setEvents(evts)
      setMarkets(mkts.markets || [])
    } finally { setLoading(false) }
  }

  useEffect(() => { reload() }, [])

  // 按联赛分组
  const grouped = {}
  for (const ev of events) {
    const league = getLeagueTag(ev.tags)
    if (!grouped[league]) grouped[league] = []
    grouped[league].push(ev)
  }
  const leagues = Object.entries(grouped)
    .sort((a, b) => {
      if (a[0] === 'Other') return 1
      if (b[0] === 'Other') return -1
      return b[1].length - a[1].length
    })

  // 默认选中第一个联赛
  const activeLeague = selectedLeague || (leagues[0] ? leagues[0][0] : null)
  const leagueEvents = activeLeague ? (grouped[activeLeague] || []) : []

  const handleSync = async () => {
    setSyncing(true)
    await syncEvents()
    await reload()
    setSyncing(false)
  }

  const handleAutoMatch = async () => {
    setMatching(true)
    setMatchResult(null)
    try {
      const res = await autoMatchAll()
      setMatchResult(res)
      await reload()
    } finally { setMatching(false) }
  }

  // 如果选中了某个赛事，显示详情页
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
            onMappingChange={reload}
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
          leagues={leagues}
          activeLeague={activeLeague}
          onSelect={setSelectedLeague}
          totalCount={events.length}
        />
        <EventDashboard
          league={activeLeague}
          events={leagueEvents}
          loading={loading}
          onSelectEvent={setSelectedEventId}
        />
      </div>
    </div>
  )
}
