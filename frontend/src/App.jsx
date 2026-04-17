import React, { useState, useEffect } from 'react'
import { fetchLeagues, fetchCricketLeagues, fetchLeagueEvents, fetchCricketEvents, syncEvents, fetchMarkets, autoMatchAll } from './api'
import HomePage from './components/HomePage.jsx'
import LeagueSidebar from './components/LeagueSidebar.jsx'
import EventDashboard from './components/EventDashboard.jsx'
import MarketOverview from './components/MarketOverview.jsx'
import SportsMarketOverview from './components/SportsMarketOverview.jsx'
import EventDetail from './components/EventDetail.jsx'
import './style.css'

// Views: home → leagues → markets → detail
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
  const [selectedEventName, setSelectedEventName] = useState('')
  const [selectedMarketLabel, setSelectedMarketLabel] = useState(null)
  const [selectedBtxMarketId, setSelectedBtxMarketId] = useState(null)
  const [currentSport, setCurrentSport] = useState('football')
  const [selectedEventData, setSelectedEventData] = useState(null)

  const loadLeagues = async (sport) => {
    setLoading(true)
    try {
      const currentSportToUse = sport || currentSport
      const fetchFunc = currentSportToUse === 'cricket' ? fetchCricketLeagues : fetchLeagues
      const [lgs, mkts] = await Promise.all([fetchFunc(), fetchMarkets()])
      setLeagues(lgs)
      setMarkets(mkts.markets || [])
      return lgs
    } finally { setLoading(false) }
  }

  const loadEventsForLeague = async (league) => {
    setLoadingEvents(true)
    try {
      // 根据当前运动类型调用不同接口
      if (currentSport === 'cricket') {
        // 从 leagues 中找到对应 league 的 sport 值
        const leagueData = leagues.find(l => l.name === league)
        const sportType = leagueData?.sport || 'crkt'
        setEvents(await fetchCricketEvents(sportType, league))
      } else {
        // 足球模块保持原有逻辑
        setEvents(await fetchLeagueEvents(league))
      }
    }
    finally { setLoadingEvents(false) }
  }

  const handleSelectSport = (sportId) => {
    if (sportId === 'football' || sportId === 'cricket') {
      // 清空旧状态
      setLeagues([])
      setEvents([])
      setSelectedLeague(null)
      
      setCurrentSport(sportId)
      setView('leagues')
      loadLeagues(sportId).then(lgs => {
        if (lgs.length > 0) {
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

  // Events page → Markets page
  const handleSelectEvent = (eventId, eventName, eventData) => {
    setSelectedEventId(eventId)
    setSelectedEventName(eventName || '')
    setSelectedEventData(eventData || null)
    setSelectedMarketLabel(null)
    setView('markets')
  }

  // Markets page → Detail page (specific btx market)
  const handleSelectMarket = (marketLabel, btxMarketId) => {
    setSelectedMarketLabel(marketLabel)
    setSelectedBtxMarketId(btxMarketId || null)
    setView('detail')
  }

  const handleBack = () => {
    if (view === 'detail') { setView('markets') }
    else if (view === 'markets') { setView('leagues') }
    else if (view === 'leagues') { setView('home') }
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await syncEvents()
      setMatchResult(res.auto_match ? { results: res.auto_match } : null)
      const lgs = await loadLeagues()
      if (selectedLeague) loadEventsForLeague(selectedLeague)
      else if (lgs.length > 0) { setSelectedLeague(lgs[0].name); loadEventsForLeague(lgs[0].name) }
    } finally { setSyncing(false) }
  }

  const handleAutoMatch = async () => {
    setMatching(true); setMatchResult(null)
    try {
      const res = await autoMatchAll()
      setMatchResult(res)
      if (selectedLeague) loadEventsForLeague(selectedLeague)
    } finally { setMatching(false) }
  }

  const leagueEntries = leagues.map(l => [l.name, { length: l.count }])
  const totalCount = leagues.reduce((s, l) => s + l.count, 0)

  // ── Home ──
  if (view === 'home') {
    return (
      <div className="app">
        <header><h1>⚡ Prediction Market Liquidity</h1></header>
        <HomePage onSelectSport={handleSelectSport} />
      </div>
    )
  }

  // ── Orderbook Detail ──
  if (view === 'detail' && selectedEventId) {
    return (
      <div className="app">
        <header>
          <h1>⚡ Prediction Market Liquidity</h1>
          <button className="sync-btn back-btn" onClick={handleBack}>← Back to Markets</button>
        </header>
        <div className="detail-fullpage">
          <EventDetail
            unifiedId={selectedEventId}
            markets={markets}
            btxMarketId={selectedBtxMarketId}
            onMappingChange={() => { if (selectedLeague) loadEventsForLeague(selectedLeague) }}
          />
        </div>
      </div>
    )
  }

  // ── Markets Overview ──
  if (view === 'markets' && selectedEventId) {
    return (
      <div className="app">
        <header>
          <h1>⚡ Prediction Market Liquidity</h1>
          <button className="sync-btn back-btn" onClick={handleBack}>← Back to Events</button>
        </header>
        <div className="detail-fullpage">
          {currentSport === 'cricket' ? (
            <SportsMarketOverview
              eventData={selectedEventData}
              displayName={selectedEventName}
              onSelectMarket={handleSelectMarket}
            />
          ) : (
            <MarketOverview
              unifiedId={selectedEventId}
              displayName={selectedEventName}
              onSelectMarket={handleSelectMarket}
              onBack={handleBack}
            />
          )}
        </div>
      </div>
    )
  }

  // ── Leagues + Events ──
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
        <LeagueSidebar leagues={leagueEntries} activeLeague={selectedLeague} onSelect={handleSelectLeague} totalCount={totalCount} />
        <EventDashboard
          league={selectedLeague}
          events={events}
          loading={loading || loadingEvents}
          onSelectEvent={(id, ev) => {
            const eventData = currentSport === 'cricket' && ev ? {
              display_name: ev.display_name,
              start_time: ev.start_time || ev.event_time,
              sport_id: ev.sport_id || 'crkt'
            } : null
            handleSelectEvent(id, ev?.display_name || '', eventData)
          }}
        />
      </div>
    </div>
  )
}
