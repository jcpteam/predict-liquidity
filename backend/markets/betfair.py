from __future__ import annotations

from datetime import datetime, timezone
from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


class BetfairAdapter(BaseMarketAdapter):
    """Betfair Exchange API 适配器"""

    name = "betfair"
    BASE_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"

    def _headers(self) -> dict:
        return {
            "X-Application": self.api_key or "",
            "X-Authentication": "",  # 需要 session token
            "Content-Type": "application/json",
        }

    async def fetch_order_book(self, market_id: str, outcome: str = "") -> OrderBook | None:
        try:
            payload = {
                "marketIds": [market_id],
                "priceProjection": {
                    "priceData": ["EX_BEST_OFFERS"],
                    "exBestOffersOverrides": {"bestPricesDepth": 10},
                },
            }
            resp = await self.client.post(
                f"{self.BASE_URL}/listMarketBook/",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            books = resp.json()
            if not books:
                return None
            runner = None
            for r in books[0].get("runners", []):
                if str(r.get("selectionId", "")) == outcome or not outcome:
                    runner = r
                    break
            if not runner:
                return None
            ex = runner.get("ex", {})
            bids = [OrderLevel(price=1 / b["price"], size=b["size"]) for b in ex.get("availableToBack", [])]
            asks = [OrderLevel(price=1 / a["price"], size=a["size"]) for a in ex.get("availableToLay", [])]
            return OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
        except Exception as e:
            print(f"[betfair] fetch_order_book error: {e}")
            return None

    async def fetch_event(self, market_id: str) -> list[MarketEvent]:
        try:
            payload = {
                "marketIds": [market_id],
                "priceProjection": {
                    "priceData": ["EX_BEST_OFFERS"],
                    "exBestOffersOverrides": {"bestPricesDepth": 10},
                },
            }
            resp = await self.client.post(
                f"{self.BASE_URL}/listMarketBook/",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            books = resp.json()
            if not books:
                return []
            book = books[0]
            # 获取市场目录以拿到 runner 名称
            cat_resp = await self.client.post(
                f"{self.BASE_URL}/listMarketCatalogue/",
                json={
                    "filter": {"marketIds": [market_id]},
                    "marketProjection": ["RUNNER_DESCRIPTION"],
                    "maxResults": 1,
                },
                headers=self._headers(),
            )
            cat_resp.raise_for_status()
            cats = cat_resp.json()
            runner_names = {}
            event_title = market_id
            if cats:
                event_title = cats[0].get("marketName", market_id)
                for r in cats[0].get("runners", []):
                    runner_names[r["selectionId"]] = r.get("runnerName", str(r["selectionId"]))

            events = []
            for runner in book.get("runners", []):
                sel_id = runner["selectionId"]
                ex = runner.get("ex", {})
                bids = [OrderLevel(price=1 / b["price"], size=b["size"]) for b in ex.get("availableToBack", [])]
                asks = [OrderLevel(price=1 / a["price"], size=a["size"]) for a in ex.get("availableToLay", [])]
                ob = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
                ltp = runner.get("lastPriceTraded")
                events.append(MarketEvent(
                    market_id=f"{market_id}:{sel_id}",
                    market_name=self.name,
                    event_title=event_title,
                    outcome=runner_names.get(sel_id, str(sel_id)),
                    order_book=ob,
                    last_price=1 / ltp if ltp else None,
                    volume_24h=book.get("totalMatched"),
                ))
            return events
        except Exception as e:
            print(f"[betfair] fetch_event error: {e}")
            return []

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        try:
            payload = {
                "filter": {
                    "eventTypeIds": ["1"],  # 1 = Soccer in Betfair
                    "marketTypeCodes": ["MATCH_ODDS"],
                    "inPlayOnly": False,
                },
                "maxResults": 50,
                "marketProjection": ["EVENT"],
            }
            resp = await self.client.post(
                f"{self.BASE_URL}/listMarketCatalogue/",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            results = []
            for cat in resp.json():
                ev = cat.get("event", {})
                title = f"{ev.get('name', '')} - {cat.get('marketName', '')}"
                if query and query.lower() not in title.lower():
                    continue
                results.append({
                    "market_id": cat.get("marketId", ""),
                    "title": title,
                    "end_date": cat.get("marketStartTime", ""),
                })
            return results
        except Exception as e:
            print(f"[betfair] search error: {e}")
            return []
