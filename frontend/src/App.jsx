import React, { useState, useEffect } from 'react'
import { fetchMappings, createMapping, deleteMapping, fetchMarkets } from './api'
import MappingManager from './components/MappingManager.jsx'
import ComparisonView from './components/ComparisonView.jsx'
import './style.css'

export default function App() {
  const [mappings, setMappings] = useState([])
  const [markets, setMarkets] = useState([])
  const [selectedMapping, setSelectedMapping] = useState(null)
  const [newName, setNewName] = useState('')
  const [newTime, setNewTime] = useState('')

  const reload = async () => {
    setMappings(await fetchMappings())
    const m = await fetchMarkets()
    setMarkets(m.markets || [])
  }

  useEffect(() => { reload() }, [])

  const handleCreate = async () => {
    if (!newName.trim()) return
    await createMapping(newName, newTime || undefined)
    setNewName('')
    setNewTime('')
    reload()
  }

  const handleDelete = async (id) => {
    await deleteMapping(id)
    if (selectedMapping === id) setSelectedMapping(null)
    reload()
  }

  return (
    <div className="app">
      <header>
        <h1>⚽ Prediction Market Liquidity Comparator</h1>
        <p className="subtitle">Compare soccer event order books across Polymarket, Kalshi, Betfair and more</p>
      </header>

      <section className="panel">
        <h2>Event Mappings</h2>
        <div className="create-form">
          <input placeholder="Event name (e.g. Champions League Final)" value={newName} onChange={e => setNewName(e.target.value)} />
          <input type="datetime-local" value={newTime} onChange={e => setNewTime(e.target.value)} />
          <button onClick={handleCreate}>+ Create Mapping</button>
        </div>
        <div className="mapping-list">
          {mappings.map(m => (
            <div key={m.unified_id} className={`mapping-card ${selectedMapping === m.unified_id ? 'active' : ''}`}>
              <div className="mapping-info" onClick={() => setSelectedMapping(m.unified_id)}>
                <strong>{m.display_name}</strong>
                <span className="badge">{Object.keys(m.mappings).length} markets</span>
                {m.event_time && <span className="time">{new Date(m.event_time).toLocaleString()}</span>}
              </div>
              <button className="btn-danger" onClick={() => handleDelete(m.unified_id)}>✕</button>
            </div>
          ))}
          {mappings.length === 0 && <p className="empty">No mappings yet. Create one above.</p>}
        </div>
      </section>

      {selectedMapping && (
        <>
          <MappingManager unifiedId={selectedMapping} markets={markets} onUpdate={reload} />
          <ComparisonView unifiedId={selectedMapping} />
        </>
      )}
    </div>
  )
}
