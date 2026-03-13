import React, { useState, useEffect } from 'react'
import { fetchEvents, syncEvents, fetchMarkets, autoMatchAll } from './api'
import EventList from './components/EventList.jsx'
import EventDetail from './components/EventDetail.jsx'
import './style.css'

export default function App() {
  const [events, setEvents] = useState([])
  const [markets, setMarkets] = useState([])
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [matching, setMatching] = useState(false)
  const [matchResult, setMatchResult] = useState(null)

  const reload = async () => {
    setLoading(true)
    try {
      const [evts, mkts] = await Promise.all([fetchEvents(), fetchMarkets()])
      setEvents(evts)
      setMarkets(mkts.markets || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { reload() }, [])

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
    } finally {
      setMatching(false)
    }
  }

  return (
    <div className="app">
      <header>
        <h1>⚽ Prediction Market Liquidity Comparator</h1>
        <p className="subtitle">Polymarket soccer events with cross-market order book comparison</p>
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
        <EventList
          events={events}
          loading={loading}
          selectedId={selectedEvent}
          onSelect={setSelectedEvent}
        />
        {selectedEvent && (
          <EventDetail
            unifiedId={selectedEvent}
            markets={markets}
            onMappingChange={reload}
          />
        )}
      </div>
    </div>
  )
}
