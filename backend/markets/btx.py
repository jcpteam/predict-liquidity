"""BTX (ex3.io) 适配器 - gRPC StreamMarketData

认证: OAuth2 client_credentials → Bearer token + x-account-id header
价格: DecimalNumber {value, dps} → actual = value / 10^dps (decimal odds)
Orderbook: back_prices = bids, lay_prices = asks
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


def _load_grpc():
    import grpc
    proto_dir = os.path.join(os.path.dirname(__file__), '..', 'proto')
    if proto_dir not in sys.path:
        sys.path.insert(0, proto_dir)
    from btx.api.v1.customer.betting import betting_api_pb2
    from btx.api.v1.customer.betting import betting_api_pb2_grpc
    return grpc, betting_api_pb2, betting_api_pb2_grpc


def _decimal_to_float(dn) -> float:
    """Convert BTX DecimalNumber {value, dps} to float"""
    if not dn or not dn.value:
        return 0.0
    return dn.value / (10 ** dn.dps) if dn.dps else float(dn.value)


class BTXAdapter(BaseMarketAdapter):
    name = "btx"
    GRPC_HOST = "api.prod.ex3.io:443"
    AUTH_URL = "https://auth.prod.ex3.io/oauth2/token"

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key)
        self.client_id = os.getenv("BTX_CLIENT_ID", "")
        self.client_secret = os.getenv("BTX_CLIENT_SECRET", "")
        self.account_id = os.getenv("BTX_ACCOUNT_ID", "")
        self._access_token: str = ""
        self._token_expires: float = 0
        self._token_lock = asyncio.Lock()
        self._channel = None
        self._stub = None
        self._grpc = None
        self._pb2 = None
        self._pb2_grpc = None

    def _ensure_grpc_loaded(self):
        if self._grpc is None:
            self._grpc, self._pb2, self._pb2_grpc = _load_grpc()

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
                data={"grant_type": "client_credentials",
                      "client_id": self.client_id,
                      "client_secret": self.client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data.get("access_token", "")
            self._token_expires = time.time() + data.get("expires_in", 3600)
            print(f"[btx] Token OK, expires_in={data.get('expires_in')}")
        except Exception as e:
            print(f"[btx] Token error: {e}")

    def _grpc_metadata(self):
        return [
            ("authorization", f"Bearer {self._access_token}"),
            ("x-account-id", self.account_id),
        ]

    async def _ensure_channel(self):
        if self._channel is not None:
            return
        self._ensure_grpc_loaded()
        creds = self._grpc.ssl_channel_credentials()
        self._channel = self._grpc.aio.secure_channel(self.GRPC_HOST, creds)
        self._stub = self._pb2_grpc.BettingApiStub(self._channel)

    async def stream_market_data(self, market_types=None, stream_prices=True, stream_ref_data=False):
        """Open StreamMarketData gRPC stream"""
        await self._ensure_token()
        await self._ensure_channel()
        if not self._access_token or not self._stub:
            return None
        if market_types is None:
            market_types = ["FOOTBALL_FULL_TIME_MATCH_ODDS"]
        req = self._pb2.StreamMarketDataRequest(
            market_types_to_stream=market_types,
            stream_prices=stream_prices,
            stream_prices_after_timestamp=0,
            stream_ref_data=stream_ref_data,
            stream_ref_data_after_timestamp=0,
        )
        return self._stub.StreamMarketData(req, metadata=self._grpc_metadata())

    def parse_price_message(self, prices_msg, runner_names=None) -> dict[str, list[MarketEvent]]:
        """Parse PriceStreamingMessage → {market_id: [MarketEvent]}"""
        result = {}
        if runner_names is None:
            runner_names = {}
        for mp in prices_msg.market_prices:
            mid = mp.market_id
            events = []
            for rp in mp.runner_prices:
                rid = rp.runner_id
                bids = []
                for bp in rp.back_prices:
                    odds = _decimal_to_float(bp.price)
                    size = _decimal_to_float(bp.size)
                    if odds > 0 and size > 0:
                        prob = round(1.0 / odds, 4) if odds > 1 else odds
                        bids.append(OrderLevel(price=prob, size=round(size, 2)))
                asks = []
                for lp in rp.lay_prices:
                    odds = _decimal_to_float(lp.price)
                    size = _decimal_to_float(lp.size)
                    if odds > 0 and size > 0:
                        prob = round(1.0 / odds, 4) if odds > 1 else odds
                        asks.append(OrderLevel(price=prob, size=round(size, 2)))
                bids.sort(key=lambda x: x.price, reverse=True)
                asks.sort(key=lambda x: x.price)
                ltp = _decimal_to_float(rp.last_traded_price) if rp.HasField('last_traded_price') else None
                ob = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
                events.append(MarketEvent(
                    market_id=f"{mid}:{rid}",
                    market_name=self.name,
                    event_title="",
                    outcome=runner_names.get(rid, rid),
                    order_book=ob,
                    last_price=round(1.0 / ltp, 4) if ltp and ltp > 1 else ltp,
                    volume_24h=None,
                ))
            if events:
                result[mid] = events
        return result

    # ── BaseMarketAdapter interface ──

    async def fetch_order_book(self, market_id: str, outcome: str = "") -> OrderBook | None:
        """Fetch orderbook for a specific BTX market (reads first price snapshot)"""
        try:
            stream = await self.stream_market_data(stream_prices=True)
            if stream is None:
                return None
            async for msg in stream:
                if msg.prices and msg.prices.market_prices:
                    parsed = self.parse_price_message(msg.prices)
                    if market_id in parsed:
                        for ev in parsed[market_id]:
                            if not outcome or ev.outcome == outcome:
                                stream.cancel()
                                return ev.order_book
                    # First price msg might not have our market, keep reading
                stream.cancel()
                break
            return None
        except Exception as e:
            print(f"[btx] fetch_order_book error: {e}")
            return None

    async def fetch_event(self, market_id: str) -> list[MarketEvent]:
        """Fetch all outcomes for a BTX market"""
        try:
            stream = await self.stream_market_data(stream_prices=True)
            if stream is None:
                return []
            async for msg in stream:
                if msg.prices and msg.prices.market_prices:
                    parsed = self.parse_price_message(msg.prices)
                    if market_id in parsed:
                        stream.cancel()
                        return parsed[market_id]
                stream.cancel()
                break
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
