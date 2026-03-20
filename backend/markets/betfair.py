"""Betfair Exchange 适配器 - 通过 The Odds API 获取 Betfair Exchange 赔率数据

The Odds API 免费 tier: 500 requests/month
- /v4/sports: 不计费
- /v4/sports/{sport}/events: 不计费
- /v4/sports/{sport}/odds: 1 credit per region per market
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


# The Odds API 支持的足球联赛 sport keys
SOCCER_SPORT_KEYS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_fa_cup",
    "soccer_efl_champ",
    "soccer_league_cup",
    "soccer_brazil_serie_a",
    "soccer_mexico_ligamx",
    "soccer_netherlands_eredivisie",
    "soccer_portugal_primeira_liga",
    "soccer_turkey_super_league",
    "soccer_australia_aleague",
    "soccer_japan_j_league",
    "soccer_korea_kleague1",
    "soccer_usa_mls",
    "soccer_conmebol_copa_libertadores",
    "soccer_uefa_europa_conference_league",
    "soccer_scotland_premiership",
]


class BetfairAdapter(BaseMarketAdapter):
    """Betfair Exchange 适配器 - 通过 The Odds API 间接获取"""

    name = "betfair"
    ODDS_API_BASE = "https://api.the-odds-api.com/v4"

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key)
        # The Odds API key (不是 Betfair 的 key)
        self.odds_api_key = api_key or os.getenv("ODDS_API_KEY", "")

    def _params(self, **extra) -> dict:
        p = {"apiKey": self.odds_api_key}
        p.update(extra)
        return p

    async def fetch_order_book(self, market_id: str, outcome: str = "") -> OrderBook | None:
        """通过 The Odds API 获取单个事件的赔率，转换为 OrderBook 格式"""
        try:
            # market_id 格式: {sport_key}:{event_id}
            parts = market_id.split(":", 1)
            if len(parts) != 2:
                return None
            sport_key, event_id = parts

            resp = await self.client.get(
                f"{self.ODDS_API_BASE}/sports/{sport_key}/events/{event_id}/odds",
                params=self._params(
                    regions="uk",
                    markets="h2h",
                    bookmakers="betfair_ex_uk",
                    oddsFormat="decimal",
                ),
            )
            resp.raise_for_status()
            data = resp.json()

            # 找 betfair exchange bookmaker
            for bm in data.get("bookmakers", []):
                if bm["key"] == "betfair_ex_uk":
                    for market in bm.get("markets", []):
                        if market["key"] == "h2h":
                            for oc in market.get("outcomes", []):
                                if not outcome or oc["name"].lower() == outcome.lower():
                                    price = oc["price"]
                                    implied_prob = 1.0 / price if price > 0 else 0
                                    bids = [OrderLevel(price=implied_prob, size=100)]
                                    asks = [OrderLevel(price=implied_prob * 1.02, size=100)]
                                    return OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
            return None
        except Exception as e:
            print(f"[betfair] fetch_order_book error: {e}")
            return None

    async def fetch_event(self, market_id: str) -> list[MarketEvent]:
        """获取事件的所有 outcomes 赔率数据
        market_id 格式: {sport_key}:{event_id}
        """
        try:
            parts = market_id.split(":", 1)
            if len(parts) != 2:
                return []
            sport_key, event_id = parts

            resp = await self.client.get(
                f"{self.ODDS_API_BASE}/sports/{sport_key}/events/{event_id}/odds",
                params=self._params(
                    regions="uk",
                    markets="h2h",
                    bookmakers="betfair_ex_uk",
                    oddsFormat="decimal",
                ),
            )
            resp.raise_for_status()
            data = resp.json()

            home = data.get("home_team", "")
            away = data.get("away_team", "")
            event_title = f"{home} vs {away}" if home and away else market_id
            commence = data.get("commence_time", "")

            events = []
            h2h_outcomes = []
            h2h_lay_outcomes = {}

            for bm in data.get("bookmakers", []):
                if bm["key"] != "betfair_ex_uk":
                    continue
                for market in bm.get("markets", []):
                    if market["key"] == "h2h":
                        h2h_outcomes = market.get("outcomes", [])
                    elif market["key"] == "h2h_lay":
                        for oc in market.get("outcomes", []):
                            h2h_lay_outcomes[oc["name"]] = oc["price"]

            for oc in h2h_outcomes:
                name = oc["name"]
                back_price = oc["price"]  # decimal odds (e.g. 2.5)
                lay_price = h2h_lay_outcomes.get(name, back_price * 1.02)

                # 转换为隐含概率 (类似 prediction market 的价格)
                back_prob = 1.0 / back_price if back_price > 0 else 0
                lay_prob = 1.0 / lay_price if lay_price > 0 else 0

                # 构建 orderbook: back = bid (买入), lay = ask (卖出)
                bids = [OrderLevel(price=round(back_prob, 4), size=round(100 / back_price, 2))]
                asks = [OrderLevel(price=round(lay_prob, 4), size=round(100 / lay_price, 2))]

                ob = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))

                events.append(MarketEvent(
                    market_id=f"{market_id}:{name}",
                    market_name=self.name,
                    event_title=event_title,
                    outcome=name,
                    order_book=ob,
                    last_price=back_prob,
                    volume_24h=None,
                ))

            return events
        except Exception as e:
            print(f"[betfair] fetch_event error: {e}")
            return []

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        """搜索所有足球联赛的即将开始的比赛"""
        if not self.odds_api_key:
            print("[betfair] No ODDS_API_KEY configured, skipping search")
            return []

        results = []
        for sport_key in SOCCER_SPORT_KEYS:
            try:
                resp = await self.client.get(
                    f"{self.ODDS_API_BASE}/sports/{sport_key}/events",
                    params=self._params(),
                )
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                events = resp.json()

                for ev in events:
                    home = ev.get("home_team", "")
                    away = ev.get("away_team", "")
                    title = f"{home} vs {away}"
                    if query and query.lower() not in title.lower():
                        continue
                    results.append({
                        "market_id": f"{sport_key}:{ev['id']}",
                        "title": title,
                        "end_date": ev.get("commence_time", ""),
                        "sport_key": sport_key,
                    })
            except Exception as e:
                # 跳过不可用的联赛
                continue

        return results

    async def fetch_all_soccer_events(self) -> list[dict]:
        """获取所有足球事件（用于自动匹配）"""
        return await self.search_soccer_events("")
