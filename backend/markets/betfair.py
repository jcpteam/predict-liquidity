"""Betfair Exchange 适配器 - 使用 Betfair Stream API (stream-api.betfair.com)

Betfair Stream API 是 SSL TCP socket 连接，使用 CRLF 分隔的 JSON 消息。
认证需要: appKey + sessionToken (通过 Betfair SSO 登录获取)

协议流程:
1. SSL TCP 连接 stream-api.betfair.com:443
2. 收到 connection 消息
3. 发送 authentication {op: "authentication", appKey, session}
4. 收到 status {statusCode: "SUCCESS"}
5. 发送 marketSubscription {op: "marketSubscription", marketFilter, marketDataFilter}
6. 收到 mcm (MarketChangeMessage) 实时数据流

REST API (api.betfair.com) 用于:
- 获取 session token (login)
- 搜索足球赛事 (listMarketCatalogue)
- 获取初始 orderbook 快照 (listMarketBook)
"""
from __future__ import annotations

import asyncio
import json
import os
import ssl
from datetime import datetime, timezone
from typing import Optional

from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


class BetfairAdapter(BaseMarketAdapter):
    """Betfair Exchange 适配器 - REST API + Stream API"""

    name = "betfair"
    REST_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"
    SSO_URL = "https://identitysso-cert.betfair.com/api/certlogin"
    SSO_URL_SIMPLE = "https://identitysso.betfair.com/api/login"
    STREAM_HOST = "stream-api.betfair.com"
    STREAM_PORT = 443

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key)
        self.app_key = api_key or os.getenv("BETFAIR_APP_KEY", "")
        self.username = os.getenv("BETFAIR_USERNAME", "")
        self.password = os.getenv("BETFAIR_PASSWORD", "")
        self.session_token: str = os.getenv("BETFAIR_SESSION_TOKEN", "")
        self._session_lock = asyncio.Lock()

    # ── Session 管理 ──

    async def _ensure_session(self):
        """确保有有效的 session token，如果没有则尝试登录"""
        if self.session_token:
            return
        async with self._session_lock:
            if self.session_token:
                return
            if not self.username or not self.password or not self.app_key:
                print("[betfair] Missing credentials (BETFAIR_APP_KEY/USERNAME/PASSWORD)")
                return
            await self._login()

    async def _login(self):
        """通过 Betfair SSO 获取 session token (非证书方式)"""
        try:
            resp = await self.client.post(
                self.SSO_URL_SIMPLE,
                data={"username": self.username, "password": self.password},
                headers={
                    "X-Application": self.app_key,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "SUCCESS":
                self.session_token = data["token"]
                print(f"[betfair] Login OK, token={self.session_token[:20]}...")
            else:
                print(f"[betfair] Login failed: {data.get('error', data)}")
        except Exception as e:
            print(f"[betfair] Login error: {e}")

    def _rest_headers(self) -> dict:
        return {
            "X-Application": self.app_key,
            "X-Authentication": self.session_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── REST API: 搜索赛事 + 获取快照 ──

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        """搜索足球赛事 (REST: listMarketCatalogue)"""
        await self._ensure_session()
        if not self.session_token:
            return []
        try:
            payload = {
                "filter": {
                    "eventTypeIds": ["1"],  # 1 = Soccer
                    "marketTypeCodes": ["MATCH_ODDS"],
                    "inPlayOnly": False,
                },
                "maxResults": 200,
                "marketProjection": ["EVENT", "MARKET_START_TIME", "RUNNER_DESCRIPTION"],
                "sort": "FIRST_TO_START",
            }
            resp = await self.client.post(
                f"{self.REST_URL}/listMarketCatalogue/",
                json=payload,
                headers=self._rest_headers(),
            )
            resp.raise_for_status()
            results = []
            for cat in resp.json():
                ev = cat.get("event", {})
                title = ev.get("name", cat.get("marketName", ""))
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

    async def fetch_order_book(self, market_id: str, outcome: str = "") -> OrderBook | None:
        """获取单个 market 的 orderbook (REST: listMarketBook)"""
        await self._ensure_session()
        if not self.session_token:
            return None
        try:
            payload = {
                "marketIds": [market_id],
                "priceProjection": {
                    "priceData": ["EX_BEST_OFFERS"],
                    "exBestOffersOverrides": {"bestPricesDepth": 10},
                },
            }
            resp = await self.client.post(
                f"{self.REST_URL}/listMarketBook/",
                json=payload,
                headers=self._rest_headers(),
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
            bids = [OrderLevel(price=1 / b["price"], size=b["size"])
                    for b in ex.get("availableToBack", []) if b["price"] > 0]
            asks = [OrderLevel(price=1 / a["price"], size=a["size"])
                    for a in ex.get("availableToLay", []) if a["price"] > 0]
            return OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
        except Exception as e:
            print(f"[betfair] fetch_order_book error: {e}")
            return None

    async def fetch_event(self, market_id: str) -> list[MarketEvent]:
        """获取事件所有 outcomes 的 orderbook (REST: listMarketBook + listMarketCatalogue)"""
        await self._ensure_session()
        if not self.session_token:
            return []
        try:
            # 获取 runner 名称
            cat_resp = await self.client.post(
                f"{self.REST_URL}/listMarketCatalogue/",
                json={
                    "filter": {"marketIds": [market_id]},
                    "marketProjection": ["RUNNER_DESCRIPTION", "EVENT"],
                    "maxResults": 1,
                },
                headers=self._rest_headers(),
            )
            cat_resp.raise_for_status()
            cats = cat_resp.json()
            runner_names = {}
            event_title = market_id
            if cats:
                ev = cats[0].get("event", {})
                event_title = ev.get("name", cats[0].get("marketName", market_id))
                for r in cats[0].get("runners", []):
                    runner_names[r["selectionId"]] = r.get("runnerName", str(r["selectionId"]))

            # 获取 orderbook
            book_resp = await self.client.post(
                f"{self.REST_URL}/listMarketBook/",
                json={
                    "marketIds": [market_id],
                    "priceProjection": {
                        "priceData": ["EX_BEST_OFFERS"],
                        "exBestOffersOverrides": {"bestPricesDepth": 10},
                    },
                },
                headers=self._rest_headers(),
            )
            book_resp.raise_for_status()
            books = book_resp.json()
            if not books:
                return []

            book = books[0]
            events = []
            for runner in book.get("runners", []):
                sel_id = runner["selectionId"]
                ex = runner.get("ex", {})
                bids = [OrderLevel(price=1 / b["price"], size=b["size"])
                        for b in ex.get("availableToBack", []) if b["price"] > 0]
                asks = [OrderLevel(price=1 / a["price"], size=a["size"])
                        for a in ex.get("availableToLay", []) if a["price"] > 0]
                ob = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
                ltp = runner.get("lastPriceTraded")
                events.append(MarketEvent(
                    market_id=f"{market_id}:{sel_id}",
                    market_name=self.name,
                    event_title=event_title,
                    outcome=runner_names.get(sel_id, str(sel_id)),
                    order_book=ob,
                    last_price=1 / ltp if ltp and ltp > 0 else None,
                    volume_24h=book.get("totalMatched"),
                ))
            return events
        except Exception as e:
            print(f"[betfair] fetch_event error: {e}")
            return []

    # ── Stream API: 实时数据流 ──

    async def stream_connect(self) -> Optional[tuple]:
        """建立 Stream API SSL TCP 连接，返回 (reader, writer)"""
        await self._ensure_session()
        if not self.session_token or not self.app_key:
            print("[betfair] Cannot connect stream: missing credentials")
            return None

        ssl_ctx = ssl.create_default_context()
        try:
            reader, writer = await asyncio.open_connection(
                self.STREAM_HOST, self.STREAM_PORT, ssl=ssl_ctx,
            )
            # 1. 读取 connection 消息
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            conn_msg = json.loads(line.decode().strip())
            if conn_msg.get("op") != "connection":
                print(f"[betfair-stream] Unexpected first message: {conn_msg}")
                writer.close()
                return None
            print(f"[betfair-stream] Connected: {conn_msg.get('connectionId', '')}")

            # 2. 发送 authentication
            auth_msg = json.dumps({
                "op": "authentication",
                "id": 1,
                "appKey": self.app_key,
                "session": self.session_token,
            }) + "\r\n"
            writer.write(auth_msg.encode())
            await writer.drain()

            # 3. 读取 status 响应
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            status_msg = json.loads(line.decode().strip())
            if status_msg.get("statusCode") != "SUCCESS":
                err = status_msg.get("errorCode", "UNKNOWN")
                print(f"[betfair-stream] Auth failed: {err} - {status_msg.get('errorMessage', '')}")
                writer.close()
                return None
            print(f"[betfair-stream] Authenticated OK")

            return reader, writer
        except Exception as e:
            print(f"[betfair-stream] Connection error: {e}")
            return None

    async def stream_subscribe_market(self, writer, market_ids: list[str],
                                       ladder_levels: int = 10):
        """发送 marketSubscription 消息"""
        sub_msg = json.dumps({
            "op": "marketSubscription",
            "id": 2,
            "marketFilter": {
                "marketIds": market_ids,
            },
            "marketDataFilter": {
                "ladderLevels": ladder_levels,
                "fields": ["EX_BEST_OFFERS", "EX_LTP", "EX_TRADED_VOL", "EX_MARKET_DEF"],
            },
            "conflateMs": 2000,  # 2 秒合并一次
        }) + "\r\n"
        writer.write(sub_msg.encode())
        await writer.drain()
        print(f"[betfair-stream] Subscribed to {len(market_ids)} markets")

    @staticmethod
    def parse_market_change(mc: dict, runner_names: dict) -> list[MarketEvent]:
        """解析 MarketChange 消息为 MarketEvent 列表"""
        market_id = mc.get("id", "")
        is_image = mc.get("img", False)
        tv = mc.get("tv")  # total volume

        # 从 marketDefinition 获取 runner 信息
        mdef = mc.get("marketDefinition")
        if mdef:
            for rd in mdef.get("runners", []):
                rid = rd.get("id")
                if rid and rid not in runner_names:
                    runner_names[rid] = str(rid)

        events = []
        for rc in mc.get("rc", []):
            sel_id = rc.get("id")
            # atb = Available To Back [[price, size], ...]
            # atl = Available To Lay [[price, size], ...]
            atb = rc.get("atb", [])
            atl = rc.get("atl", [])
            # batb/batl = Best Available (level, price, size)
            batb = rc.get("batb", [])
            batl = rc.get("batl", [])
            ltp = rc.get("ltp")

            # 优先用 atb/atl (完整深度), 否则用 batb/batl (best offers)
            if atb:
                bids = [OrderLevel(price=round(1 / p, 4), size=round(s, 2))
                        for p, s in atb if p > 0 and s > 0]
            elif batb:
                bids = [OrderLevel(price=round(1 / p, 4), size=round(s, 2))
                        for _, p, s in batb if p > 0 and s > 0]
            else:
                bids = []

            if atl:
                asks = [OrderLevel(price=round(1 / p, 4), size=round(s, 2))
                        for p, s in atl if p > 0 and s > 0]
            elif batl:
                asks = [OrderLevel(price=round(1 / p, 4), size=round(s, 2))
                        for _, p, s in batl if p > 0 and s > 0]
            else:
                asks = []

            # 按价格排序: bids 降序, asks 升序
            bids.sort(key=lambda x: x.price, reverse=True)
            asks.sort(key=lambda x: x.price)

            ob = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
            events.append(MarketEvent(
                market_id=f"{market_id}:{sel_id}",
                market_name="betfair",
                event_title="",
                outcome=runner_names.get(sel_id, str(sel_id)),
                order_book=ob,
                last_price=round(1 / ltp, 4) if ltp and ltp > 0 else None,
                volume_24h=tv,
            ))
        return events
