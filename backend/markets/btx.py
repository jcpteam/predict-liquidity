"""BTX (ex3.io) 适配器 - gRPC StreamMarketData

认证: OAuth2 client_credentials → Bearer token + x-account-id header
价格: DecimalNumber {value, dps} → actual = value / 10^dps (decimal odds)
Orderbook: back_prices = bids, lay_prices = asks
Runner names: 从 ref_data.competitors 获取，缓存在 _runner_names
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
    if not dn or not dn.value:
        return 0.0
    return dn.value / (10 ** dn.dps) if dn.dps else float(dn.value)


def _get_en_name(display_names) -> str:
    """Extract English name from repeated LanguageName"""
    for dn in display_names:
        if dn.language_code == "en" and "*" in dn.region_codes:
            return dn.name
    for dn in display_names:
        if dn.language_code == "en":
            return dn.name
    if display_names:
        return display_names[0].name
    return ""


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
        # Runner ID → display name cache (loaded from ref_data)
        self._runner_names: dict[str, str] = {}
        self._runner_names_loaded = False

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
        opts = [('grpc.max_receive_message_length', 50 * 1024 * 1024)]  # 50MB
        self._channel = self._grpc.aio.secure_channel(self.GRPC_HOST, creds, options=opts)
        self._stub = self._pb2_grpc.BettingApiStub(self._channel)

    async def _load_runner_names(self):
        """Load competitor/runner names from ref_data stream (once)"""
        if self._runner_names_loaded:
            return
        try:
            await self._ensure_token()
            await self._ensure_channel()
            if not self._stub:
                return
            req = self._pb2.StreamMarketDataRequest(
                market_types_to_stream=["FOOTBALL_FULL_TIME_MATCH_ODDS"],
                stream_ref_data=True,
                stream_ref_data_after_timestamp=0,
                stream_prices=False,
            )
            stream = self._stub.StreamMarketData(req, metadata=self._grpc_metadata())
            async for msg in stream:
                if msg.ref_data and msg.ref_data.timestamp > 0:
                    # Competitors → runner names
                    for comp in msg.ref_data.competitors:
                        name = _get_en_name(comp.display_names)
                        if name:
                            self._runner_names[comp.id] = name
                    # Special runners
                    self._runner_names["DRAW"] = "Draw"
                    self._runner_names["OVER"] = "Over"
                    self._runner_names["UNDER"] = "Under"
                    # Correct score runners (e.g. "0-0", "1-0", etc)
                    for mkt in msg.ref_data.markets:
                        for runner in mkt.runners:
                            rid = runner.id
                            if rid and rid not in self._runner_names:
                                # Score format like "0-0", "1-2", etc
                                if "-" in rid and len(rid) <= 5:
                                    self._runner_names[rid] = rid
                                elif rid.startswith("ANY_OTHER"):
                                    self._runner_names[rid] = rid.replace("_", " ").title()
                    if self._runner_names:
                        print(f"[btx] Loaded {len(self._runner_names)} runner names")
                        self._runner_names_loaded = True
                        stream.cancel()
                        return
            stream.cancel()
        except Exception as e:
            print(f"[btx] Failed to load runner names: {e}")

    async def stream_market_data(self, market_types=None, stream_prices=True, stream_ref_data=False):
        """Open StreamMarketData gRPC stream"""
        await self._ensure_token()
        await self._ensure_channel()
        if not self._stub:
            return None
        if market_types is None:
            market_types = [
                "FOOTBALL_FULL_TIME_MATCH_ODDS",
                "FOOTBALL_FULL_TIME_TOTAL_GOALS_OVER_UNDER",
                "FOOTBALL_FULL_TIME_ASIAN_HANDICAP",
                "FOOTBALL_FULL_TIME_ASIAN_HANDICAP_TOTAL_GOALS",
                "FOOTBALL_FULL_TIME_CORRECT_SCORE",
            ]
        req = self._pb2.StreamMarketDataRequest(
            market_types_to_stream=market_types,
            stream_prices=stream_prices,
            stream_prices_after_timestamp=0,
            stream_ref_data=stream_ref_data,
            stream_ref_data_after_timestamp=0,
            disable_synthetic_prices=True,
            market_prices_choice=2,
        )
        return self._stub.StreamMarketData(req, metadata=self._grpc_metadata())

    def parse_price_message(self, prices_msg, runner_names=None) -> dict[str, list[MarketEvent]]:
        """Parse PriceStreamingMessage → {market_id: [MarketEvent]}"""
        result = {}
        names = runner_names or self._runner_names
        for mp in prices_msg.market_prices:
            mid = mp.market_id
            market_traded = mp.traded  # total matched volume for this market (USD)
            events = []
            for rp in mp.decimal_prices:
                rid = rp.runner_id
                runner_traded = rp.traded if rp.traded else 0
                # Get handicap value for Asian Handicap / Goal Lines
                handicap_str = ""
                if rp.HasField('handicap') and rp.handicap.value != 0:
                    hval = rp.handicap.value
                    hdps = rp.handicap.dps
                    # Handle unsigned int64 overflow for negative values
                    if hval > 2**63:
                        hval = hval - 2**64
                    h = hval / (10 ** hdps) if hdps else float(hval)
                    handicap_str = f" ({'+' if h > 0 else ''}{h:.1f})" if h != 0 else ""
                bids = []
                for bp in rp.lay_prices:
                    odds = _decimal_to_float(bp.price)
                    size = _decimal_to_float(bp.size)
                    if odds > 0 and size > 0:
                        prob = round(1.0 / odds, 4) if odds > 1 else odds
                        bids.append(OrderLevel(price=prob, size=round(size, 2)))
                asks = []
                for lp in rp.back_prices:
                    odds = _decimal_to_float(lp.price)
                    size = _decimal_to_float(lp.size)
                    if odds > 0 and size > 0:
                        prob = round(1.0 / odds, 4) if odds > 1 else odds
                        asks.append(OrderLevel(price=prob, size=round(size, 2)))
                bids.sort(key=lambda x: x.price, reverse=True)
                asks.sort(key=lambda x: x.price)
                ltp = _decimal_to_float(rp.last_traded_price) if rp.HasField('last_traded_price') else None
                ob = OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
                display_name = names.get(rid, rid) + handicap_str
                events.append(MarketEvent(
                    market_id=f"{mid}:{rid}",
                    market_name=self.name,
                    event_title="",
                    outcome=display_name,
                    order_book=ob,
                    last_price=round(1.0 / ltp, 4) if ltp and ltp > 1 else ltp,
                    volume_24h=float(runner_traded) if runner_traded else None,
                ))
            if events:
                result[mid] = events
        return result

    # ── BaseMarketAdapter interface ──

    async def fetch_order_book(self, market_id: str, outcome: str = "") -> OrderBook | None:
        try:
            await self._load_runner_names()
            stream = await self.stream_market_data(stream_prices=True)
            if stream is None:
                return None
            import time
            t0 = time.time()
            async for msg in stream:
                if time.time() - t0 > 30:
                    break
                if msg.prices and msg.prices.market_prices:
                    parsed = self.parse_price_message(msg.prices)
                    if market_id in parsed:
                        for ev in parsed[market_id]:
                            if not outcome or ev.outcome == outcome:
                                if ev.order_book.bids or ev.order_book.asks:
                                    stream.cancel()
                                    return ev.order_book
            stream.cancel()
            return None
        except Exception as e:
            print(f"[btx] fetch_order_book error: {e}")
            return None

    async def fetch_event(self, market_id: str) -> list[MarketEvent]:
        """Fetch all outcomes for a BTX market.
        BTX initial price snapshot can take 15-20s to arrive.
        """
        try:
            await self._load_runner_names()
            stream = await self.stream_market_data(stream_prices=True)
            if stream is None:
                return []
            import time
            t0 = time.time()
            best_events = []
            async for msg in stream:
                if time.time() - t0 > 30:
                    break
                if msg.prices and msg.prices.market_prices:
                    parsed = self.parse_price_message(msg.prices)
                    if market_id in parsed:
                        events = parsed[market_id]
                        has_data = any(len(e.order_book.bids) > 0 or len(e.order_book.asks) > 0 for e in events)
                        if has_data:
                            stream.cancel()
                            return events
                        elif not best_events:
                            best_events = events
            stream.cancel()
            return best_events
        except Exception as e:
            print(f"[btx] fetch_event error: {e}")
            return []

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        return []

    # ── Cricket-specific methods ──

    CRICKET_MARKET_TYPES = [
        "CRICKET_MATCH_ODDS",
        "CRICKET_MATCH_ODDS_WITH_DRAW",
        "CRICKET_COMPLETED_MATCH",
        "CRICKET_TIED_MATCH",
        "CRICKET_INNINGS_SESSION_TOTAL_LINE",
        "CRICKET_INNINGS_TOTAL_LINE",
    ]

    async def fetch_cricket_event(self, market_id: str) -> list[MarketEvent]:
        """Fetch orderbook for a cricket market using cricket-specific market types."""
        try:
            await self._load_runner_names()
            stream = await self.stream_market_data(
                market_types=self.CRICKET_MARKET_TYPES,
                stream_prices=True,
            )
            if stream is None:
                return []
            import time
            t0 = time.time()
            best_events = []
            async for msg in stream:
                if time.time() - t0 > 30:
                    break
                if msg.prices and msg.prices.market_prices:
                    parsed = self.parse_price_message(msg.prices)
                    if market_id in parsed:
                        events = parsed[market_id]
                        has_data = any(len(e.order_book.bids) > 0 or len(e.order_book.asks) > 0 for e in events)
                        if has_data:
                            stream.cancel()
                            return events
                        elif not best_events:
                            best_events = events
            stream.cancel()
            return best_events
        except Exception as e:
            print(f"[btx] fetch_cricket_event error: {e}")
            return []

    async def close(self):
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
        await super().close()
