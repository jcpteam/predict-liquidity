from datetime import datetime, timezone
from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


class KalshiAdapter(BaseMarketAdapter):
    """Kalshi API 适配器"""

    name = "kalshi"
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    async def fetch_order_book(self, ticker: str, outcome: str = "") -> OrderBook | None:
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/markets/{ticker}/orderbook",
                params={"depth": 20},
            )
            resp.raise_for_status()
            data = resp.json().get("orderbook", {})
            bids = [OrderLevel(price=float(b[0]) / 100, size=float(b[1])) for b in data.get("yes", [])]
            asks = [OrderLevel(price=float(a[0]) / 100, size=float(a[1])) for a in data.get("no", [])]
            return OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
        except Exception as e:
            print(f"[kalshi] fetch_order_book error: {e}")
            return None

    async def fetch_event(self, ticker: str) -> list[MarketEvent]:
        try:
            resp = await self.client.get(f"{self.BASE_URL}/markets/{ticker}")
            resp.raise_for_status()
            m = resp.json().get("market", {})
            ob = await self.fetch_order_book(ticker)
            events = []
            for outcome_label in ["Yes", "No"]:
                events.append(MarketEvent(
                    market_id=ticker,
                    market_name=self.name,
                    event_title=m.get("title", ""),
                    outcome=outcome_label,
                    order_book=ob if outcome_label == "Yes" else None,
                    last_price=float(m.get("last_price", 0)) / 100 if outcome_label == "Yes" else 1 - float(m.get("last_price", 0)) / 100,
                    volume_24h=float(m.get("volume_24h", 0)),
                ))
            return events
        except Exception as e:
            print(f"[kalshi] fetch_event error: {e}")
            return []

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        try:
            params = {"status": "open", "limit": 50}
            if query:
                params["title"] = query
            resp = await self.client.get(f"{self.BASE_URL}/events", params=params)
            resp.raise_for_status()
            results = []
            for ev in resp.json().get("events", []):
                title = ev.get("title", "").lower()
                if "soccer" in title or "football" in title or "fifa" in title or "premier" in title or "champions" in title or query.lower() in title:
                    results.append({
                        "market_id": ev.get("ticker", ev.get("event_ticker", "")),
                        "title": ev.get("title", ""),
                        "end_date": ev.get("close_time", ""),
                    })
            return results
        except Exception as e:
            print(f"[kalshi] search error: {e}")
            return []
