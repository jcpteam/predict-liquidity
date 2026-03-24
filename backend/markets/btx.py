"""BTX (ex3.io) 适配器 - 使用 gRPC API

gRPC 端点: api.prod.ex3.io:443
认证端点: https://auth.prod.ex3.io/oauth2/token

服务: btx.api.v1.customer.betting.BettingApi
- StreamMarketData: 实时市场数据流 (server streaming)

认证流程:
1. OAuth2 client_credentials 获取 access_token
2. gRPC metadata 中携带 Bearer token

注意: grpc 和 proto 模块延迟导入，避免未安装 grpcio 时阻塞整个应用启动
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional, AsyncIterator

from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


def _load_grpc():
    """延迟加载 grpc 和 proto 模块"""
    import grpc
    proto_dir = os.path.join(os.path.dirname(__file__), '..', 'proto')
    if proto_dir not in sys.path:
        sys.path.insert(0, proto_dir)
    from btx.api.v1.customer.betting import betting_api_pb2
    from btx.api.v1.customer.betting import betting_api_pb2_grpc
    return grpc, betting_api_pb2, betting_api_pb2_grpc


class BTXAdapter(BaseMarketAdapter):
    """BTX (ex3.io) 适配器 - gRPC API"""

    name = "btx"
    GRPC_HOST = "api.prod.ex3.io:443"
    AUTH_URL = "https://auth.prod.ex3.io/oauth2/token"

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key)
        self.client_id = os.getenv("BTX_CLIENT_ID", "")
        self.client_secret = os.getenv("BTX_CLIENT_SECRET", "")
        self._access_token: str = ""
        self._token_expires: float = 0
        self._token_lock = asyncio.Lock()
        self._channel = None
        self._stub = None
        self._grpc = None
        self._pb2 = None
        self._pb2_grpc = None

    def _ensure_grpc_loaded(self):
        """确保 grpc 模块已加载"""
        if self._grpc is None:
            self._grpc, self._pb2, self._pb2_grpc = _load_grpc()

    # ── OAuth2 认证 ──

    async def _ensure_token(self):
        if self._access_token and time.time() < self._token_expires - 60:
            return
        async with self._token_lock:
            if self._access_token and time.time() < self._token_expires - 60:
                return
            await self._fetch_token()

    async def _fetch_token(self):
        if not self.client_id or not self.client_secret:
            print("[btx] Missing BTX_CLIENT_ID or BTX_CLIENT_SECRET")
            return
        try:
            resp = await self.client.post(
                self.AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data.get("access_token", "")
            expires_in = data.get("expires_in", 3600)
            self._token_expires = time.time() + expires_in
            print(f"[btx] OAuth2 token obtained, expires in {expires_in}s")
        except Exception as e:
            print(f"[btx] OAuth2 token error: {e}")

    def _grpc_metadata(self) -> list[tuple[str, str]]:
        return [("authorization", f"Bearer {self._access_token}")]

    # ── gRPC Channel 管理 ──

    async def _ensure_channel(self):
        if self._channel is not None:
            return
        self._ensure_grpc_loaded()
        credentials = self._grpc.ssl_channel_credentials()
        self._channel = self._grpc.aio.secure_channel(self.GRPC_HOST, credentials)
        self._stub = self._pb2_grpc.BettingApiStub(self._channel)
        print(f"[btx] gRPC channel created to {self.GRPC_HOST}")

    # ── StreamMarketData ──

    async def stream_market_data(self, market_ids: list[str]) -> AsyncIterator:
        await self._ensure_token()
        await self._ensure_channel()
        if not self._access_token or not self._stub:
            return None
        request = self._pb2.StreamMarketDataRequest(market_ids=market_ids)
        return self._stub.StreamMarketData(request, metadata=self._grpc_metadata())

    def parse_market_update(self, update) -> list[MarketEvent]:
        events = []
        market_id = update.market_id
        event_name = update.event_name or market_id
        for runner in update.runners:
            bids = [OrderLevel(price=round(1 / p.price, 4) if p.price > 0 else 0,
                               size=round(p.size, 2))
                    for p in runner.back_prices if p.price > 0 and p.size > 0]
            asks = [OrderLevel(price=round(1 / p.price, 4) if p.price > 0 else 0,
                               size=round(p.size, 2))
                    for p in runner.lay_prices if p.price > 0 and p.size > 0]
            bids.sort(key=lambda x: x.price, reverse=True)
            asks.sort(key=lambda x: x.price)
            ob = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
            ltp = runner.last_traded_price
            events.append(MarketEvent(
                market_id=f"{market_id}:{runner.runner_id}",
                market_name=self.name,
                event_title=event_name,
                outcome=runner.runner_name or runner.runner_id,
                order_book=ob,
                last_price=round(1 / ltp, 4) if ltp and ltp > 0 else None,
                volume_24h=update.total_matched or runner.total_matched,
            ))
        return events

    # ── BaseMarketAdapter 接口 ──

    async def fetch_order_book(self, market_id: str, outcome: str = "") -> OrderBook | None:
        try:
            stream = await self.stream_market_data([market_id])
            if stream is None:
                return None
            async for update in stream:
                for runner in update.runners:
                    if outcome and runner.runner_id != outcome and runner.runner_name != outcome:
                        continue
                    bids = [OrderLevel(price=round(1 / p.price, 4), size=round(p.size, 2))
                            for p in runner.back_prices if p.price > 0 and p.size > 0]
                    asks = [OrderLevel(price=round(1 / p.price, 4), size=round(p.size, 2))
                            for p in runner.lay_prices if p.price > 0 and p.size > 0]
                    stream.cancel()
                    return OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
                stream.cancel()
                break
            return None
        except Exception as e:
            print(f"[btx] fetch_order_book error: {e}")
            return None

    async def fetch_event(self, market_id: str) -> list[MarketEvent]:
        try:
            stream = await self.stream_market_data([market_id])
            if stream is None:
                return []
            async for update in stream:
                events = self.parse_market_update(update)
                stream.cancel()
                return events
            return []
        except Exception as e:
            print(f"[btx] fetch_event error: {e}")
            return []

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        return []

    async def close(self):
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
        await super().close()
