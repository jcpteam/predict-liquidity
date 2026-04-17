import React from 'react'

const CATEGORIES = [
  { id: 'sports', name: 'Sports', icon: '🏆', active: true },
  { id: 'politics', name: 'Politics', icon: '🏛️', active: false },
  { id: 'crypto', name: 'Crypto', icon: '₿', active: false },
  { id: 'culture', name: 'Culture', icon: '🎬', active: false },
  { id: 'science', name: 'Science', icon: '🔬', active: false },
  { id: 'economics', name: 'Economics', icon: '📈', active: false },
  { id: 'weather', name: 'Weather', icon: '🌤️', active: false },
]

const SPORTS = [
  { id: 'football', name: 'Football', icon: '⚽', desc: 'EPL, La Liga, UCL, Serie A & more', available: true },
  { id: 'cricket', name: 'Cricket', icon: '🏏', desc: 'IPL, Test Matches, T20 World Cup', available: true },
  { id: 'basketball', name: 'NBA', icon: '🏀', desc: 'NBA, EuroLeague, FIBA', available: false },
  { id: 'tennis', name: 'Tennis', icon: '🎾', desc: 'Grand Slams, ATP, WTA', available: false },
  { id: 'baseball', name: 'Baseball', icon: '⚾', desc: 'MLB, NPB, KBO', available: false },
  { id: 'hockey', name: 'Ice Hockey', icon: '🏒', desc: 'NHL, KHL, SHL', available: false },
  { id: 'mma', name: 'MMA / UFC', icon: '🥊', desc: 'UFC, Bellator, ONE Championship', available: false },
  { id: 'rugby', name: 'Rugby', icon: '🏉', desc: 'Six Nations, Rugby World Cup', available: false },
  { id: 'f1', name: 'Formula 1', icon: '🏎️', desc: 'F1 Grand Prix, Constructors', available: false },
  { id: 'golf', name: 'Golf', icon: '⛳', desc: 'PGA Tour, The Masters, Ryder Cup', available: false },
  { id: 'esports', name: 'Esports', icon: '🎮', desc: 'LoL, CS2, Dota 2, Valorant', available: false },
  { id: 'horse', name: 'Horse Racing', icon: '🐎', desc: 'Royal Ascot, Kentucky Derby', available: false },
]

export default function HomePage({ onSelectSport }) {
  return (
    <div className="home-page">
      {/* Category tabs */}
      <div className="home-tabs">
        {CATEGORIES.map(cat => (
          <div
            key={cat.id}
            className={`home-tab ${cat.active ? 'active' : 'disabled'}`}
            title={cat.active ? '' : 'Coming soon'}
          >
            <span className="home-tab-icon">{cat.icon}</span>
            <span className="home-tab-name">{cat.name}</span>
          </div>
        ))}
      </div>

      {/* Sports grid */}
      <div className="home-content">
        <h2 className="home-section-title">Sports Markets</h2>
        <p className="home-section-desc">Compare orderbook liquidity across prediction markets</p>
        <div className="sports-grid">
          {SPORTS.map(sport => (
            <div
              key={sport.id}
              className={`sport-card ${sport.available ? '' : 'sport-card-disabled'}`}
              onClick={() => sport.available && onSelectSport(sport.id)}
              role={sport.available ? 'button' : undefined}
              tabIndex={sport.available ? 0 : undefined}
              onKeyDown={e => e.key === 'Enter' && sport.available && onSelectSport(sport.id)}
            >
              <div className="sport-card-icon">{sport.icon}</div>
              <div className="sport-card-body">
                <div className="sport-card-name">{sport.name}</div>
                <div className="sport-card-desc">{sport.desc}</div>
              </div>
              {sport.available ? (
                <div className="sport-card-arrow">→</div>
              ) : (
                <div className="sport-card-soon">Soon</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
