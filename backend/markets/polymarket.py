from datetime import datetime, timezone
from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


class PolymarketAdapter(BaseMarketAdapter):
    """Polymarket CLOB API 适配器"""

    name = "polymarket"
    BASE_URL = "https://clob.polymarket.com"
    GAMMA_URL = "https://gamma-api.polymarket.com"

    async def fetch_order_book(self, token_id: str, outcome: str = "") -> OrderBook | None:
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/book",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
            data = resp.json()
            bids = [OrderLevel(price=float(b["price"]), size=float(b["size"])) for b in data.get("bids", [])]
            asks = [OrderLevel(price=float(a["price"]), size=float(a["size"])) for a in data.get("asks", [])]
            return OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
        except Exception as e:
            print(f"[polymarket] fetch_order_book error: {e}")
            return None

    async def fetch_event(self, condition_id: str) -> list[MarketEvent]:
        try:
            resp = await self.client.get(
                f"{self.GAMMA_URL}/markets",
                params={"condition_id": condition_id},
            )
            resp.raise_for_status()
            markets = resp.json()
            if not isinstance(markets, list):
                markets = [markets]
            events = []
            for m in markets:
                for token in m.get("tokens", []):
                    outcome_label = token.get("outcome", "Unknown")
                    ob = await self.fetch_order_book(token["token_id"])
                    events.append(MarketEvent(
                        market_id=token["token_id"],
                        market_name=self.name,
                        event_title=m.get("question", ""),
                        outcome=outcome_label,
                        order_book=ob,
                        last_price=float(token.get("price", 0)),
                        volume_24h=float(m.get("volume24hr", 0)),
                    ))
            return events
        except Exception as e:
            print(f"[polymarket] fetch_event error: {e}")
            return []

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        try:
            resp = await self.client.get(
                f"{self.GAMMA_URL}/events",
                params={"tag": "soccer", "closed": "false", "limit": 50},
            )
            resp.raise_for_status()
            results = []
            for ev in resp.json():
                results.append({
                    "market_id": ev.get("condition_id", ev.get("id", "")),
                    "title": ev.get("title", ""),
                    "end_date": ev.get("end_date_iso", ""),
                })
            return results
        except Exception as e:
            print(f"[polymarket] search error: {e}")
            return []
