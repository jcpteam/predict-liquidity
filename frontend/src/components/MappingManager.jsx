import React, { useState, useEffect } from 'react'
import { fetchMappings, addMarketToMapping, removeMarketFromMapping, searchMarketEvents } from '../api'

export default function MappingManager({ unifiedId, markets, onUpdate }) {
  const [mapping, setMapping] = useState(null)
  const [selectedMarket, setSelectedMarket] = useState(markets[0] || '')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [manualId, setManualId] = useState('')

  useEffect(() => {
    fetchMappings().then(all => {
      const found = all.find(m => m.unified_id === unifiedId)
      setMapping(found || null)
    })
  }, [unifiedId])

  const handleSearch = async () => {
    if (!selectedMarket) return
    const results = await searchMarketEvents(selectedMarket, searchQuery)
    setSearchResults(results)
  }

  const handleAdd = async (marketEventId) => {
    await addMarketToMapping(unifiedId, selectedMarket, marketEventId)
    onUpdate()
    setSearchResults([])
    // refresh local
    const all = await fetchMappings()
    setMapping(all.find(m => m.unified_id === unifiedId))
  }

  const handleRemove = async (marketName) => {
    await removeMarketFromMapping(unifiedId, marketName)
    onUpdate()
    const all = await fetchMappings()
    setMapping(all.find(m => m.unified_id === unifiedId))
  }

  if (!mapping) return null

  return (
    <section className="panel">
      <h2>Manage Markets for: {mapping.display_name}</h2>

      <div className="linked-markets">
        <h3>Linked Markets</h3>
        {Object.entries(mapping.mappings).length === 0 && <p className="empty">No markets linked yet.</p>}
        {Object.entries(mapping.mappings).map(([name, id]) => (
          <div key={name} className="linked-item">
            <span className="market-badge">{name}</span>
            <code>{id}</code>
            <button className="btn-danger btn-sm" onClick={() => handleRemove(name)}>Remove</button>
          </div>
        ))}
      </div>

      <div className="add-market">
        <h3>Add Market</h3>
        <div className="add-market-row">
          <select value={selectedMarket} onChange={e => setSelectedMarket(e.target.value)}>
            {markets.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <input placeholder="Search events..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
          <button onClick={handleSearch}>Search</button>
        </div>
        <div className="add-market-row">
          <input placeholder="Or paste market/event ID directly" value={manualId} onChange={e => setManualId(e.target.value)} style={{flex: 1}} />
          <button onClick={() => { if (manualId) handleAdd(manualId); setManualId('') }}>Add by ID</button>
        </div>
        {searchResults.length > 0 && (
          <div className="search-results">
            {searchResults.map((r, i) => (
              <div key={i} className="search-item" onClick={() => handleAdd(r.market_id)}>
                <span>{r.title}</span>
                <code>{r.market_id}</code>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
