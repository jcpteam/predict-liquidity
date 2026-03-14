from __future__ import annotations

import json
from datetime import datetime, timezone
from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


class PolymarketAdapter(BaseMarketAdapter):
    """Polymarket CLOB API 适配器"""

    name = "polymarket"
    BASE_URL = "https://clob.polymarket.com"
    GAMMA_URL = "https://gamma-api.polymarket.com"

    # 足球相关的 tag_id (从 /sports 端点获取)
    SOCCER_TAG_IDS = [
        100350,  # Soccer (通用)
        82,      # EPL
        780,     # La Liga
        1494,    # Bundesliga
        100977,  # UCL
        100100,  # MLS
        102974,  # Africa Cup
        64,      # FIFA
    ]

    async def fetch_all_soccer_events(self) -> list[dict]:
        """获取 Polymarket 上所有活跃的足球赛事（以 tag_id=100350 为主）"""
        all_events = []
        offset = 0
        limit = 100
        while True:
            try:
                resp = await self.client.get(
                    f"{self.GAMMA_URL}/events",
                    params={
                        "tag_id": 100350,
                        "active": "true",
                        "closed": "false",
                        "limit": limit,
                        "offset": offset,
                        "order": "liquidity",
                        "ascending": "false",
                    },
                )
                resp.raise_for_status()
                events = resp.json()
                if not events:
                    break
                all_events.extend(events)
                if len(events) < limit:
                    break
                offset += limit
            except Exception as e:
                print(f"[polymarket] fetch_all_soccer_events error at offset {offset}: {type(e).__name__}: {e}")
                import traceback; traceback.print_exc()
                break
        return all_events

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

    async def fetch_event_orderbooks(self, event_id: str) -> list[MarketEvent]:
        """根据 event_id 获取该事件下所有 market 的 order book（批量获取）"""
        try:
            resp = await self.client.get(f"{self.GAMMA_URL}/events/{event_id}")
            resp.raise_for_status()
            event = resp.json()
            is_neg_risk = event.get("negRisk", False)

            # 收集所有 token 元数据，negRisk 事件只取 Yes token (index 0)
            token_meta = []  # [(token_id, outcome, last_price, question, volume)]
            for m in event.get("markets", []):
                if not m.get("enableOrderBook", True):
                    continue
                token_ids_raw = m.get("clobTokenIds", "[]")
                token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
                outcomes_raw = m.get("outcomes", "[]")
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                prices_raw = m.get("outcomePrices", "[]")
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                question = m.get("question", m.get("groupItemTitle", ""))
                vol = m.get("volume24hr")

                for idx, token_id in enumerate(token_ids):
                    # negRisk 事件: 只有 Yes token (idx=0) 有 order book
                    if is_neg_risk and idx > 0:
                        continue
                    outcome_label = outcomes[idx] if idx < len(outcomes) else f"Outcome {idx}"
                    last_price = float(prices[idx]) if idx < len(prices) else None
                    group_title = m.get("groupItemTitle", "")
                    display_title = group_title if group_title else question
                    token_meta.append((token_id, outcome_label, last_price, display_title, vol))

            # 批量获取 order book（POST /books，每批最多 50 个）
            ob_map: dict[str, OrderBook | None] = {}
            batch_size = 50
            for i in range(0, len(token_meta), batch_size):
                batch = token_meta[i:i + batch_size]
                batch_ids = [t[0] for t in batch]
                try:
                    book_resp = await self.client.post(
                        f"{self.BASE_URL}/books",
                        json=[{"token_id": tid} for tid in batch_ids],
                        timeout=20.0,
                    )
                    book_resp.raise_for_status()
                    books = book_resp.json()
                    for idx_b, book_data in enumerate(books):
                        tid = batch_ids[idx_b]
                        bids = [OrderLevel(price=float(b["price"]), size=float(b["size"])) for b in book_data.get("bids", [])]
                        asks = [OrderLevel(price=float(a["price"]), size=float(a["size"])) for a in book_data.get("asks", [])]
                        ob_map[tid] = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
                except Exception as e:
                    print(f"[polymarket] batch book fetch error: {e}")
                    for tid in batch_ids:
                        ob_map.setdefault(tid, None)

            results = []
            for token_id, outcome_label, last_price, display_title, vol in token_meta:
                results.append(MarketEvent(
                    market_id=token_id,
                    market_name=self.name,
                    event_title=display_title,
                    outcome=outcome_label,
                    order_book=ob_map.get(token_id),
                    last_price=last_price,
                    volume_24h=vol,
                ))
            return results
        except Exception as e:
            print(f"[polymarket] fetch_event_orderbooks error: {e}")
            return []

    # ── 保留基类接口兼容 ──

    async def fetch_event(self, market_id: str) -> list[MarketEvent]:
        return await self.fetch_event_orderbooks(market_id)

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        events = await self.fetch_all_soccer_events()
        results = []
        for ev in events:
            title = ev.get("title", "")
            if query and query.lower() not in title.lower():
                continue
            results.append({
                "market_id": str(ev.get("id", "")),
                "title": title,
                "end_date": ev.get("endDate", ""),
            })
        return results
