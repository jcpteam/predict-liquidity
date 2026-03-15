from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from models import OrderBook, OrderLevel, MarketEvent
from .base import BaseMarketAdapter


class KalshiAdapter(BaseMarketAdapter):
    """Kalshi API 适配器 - 通过 series + events 获取足球赛事"""

    name = "kalshi"
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self, api_key: str | None = None):
        super().__init__(api_key)
        self._soccer_series: list[dict] = []
        self._series_fetched: bool = False

    async def _fetch_soccer_series(self) -> list[dict]:
        """获取所有带 'soccer' tag 的 series"""
        if self._soccer_series and self._series_fetched:
            return self._soccer_series

        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/series",
                timeout=30.0,
            )
            resp.raise_for_status()
            all_series = resp.json().get("series", [])
            self._soccer_series = [
                s for s in all_series
                if "soccer" in [t.lower() for t in (s.get("tags") or [])]
            ]
            self._series_fetched = True
            print(f"[kalshi] Found {len(self._soccer_series)} soccer series")
            return self._soccer_series
        except Exception as e:
            print(f"[kalshi] _fetch_soccer_series error: {e}")
            return []

    async def _fetch_events_for_series(self, series_ticker: str) -> list[dict]:
        """获取某个 series 下所有 open 的 events（cursor 分页，带 429 重试）"""
        events = []
        cursor = None
        while True:
            params: dict = {
                "series_ticker": series_ticker,
                "status": "open",
                "with_nested_markets": "true",
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            for attempt in range(3):
                try:
                    resp = await self.client.get(
                        f"{self.BASE_URL}/events",
                        params=params,
                        timeout=20.0,
                    )
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        print(f"[kalshi] 429 for {series_ticker}, retry in {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    batch = data.get("events", [])
                    events.extend(batch)
                    cursor = data.get("cursor")
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"[kalshi] _fetch_events_for_series({series_ticker}) error: {e}")
                    else:
                        await asyncio.sleep(1)
            else:
                break  # 3次重试都失败
            if not cursor or not batch:
                break
        return events

    async def search_soccer_events(self, query: str = "") -> list[dict]:
        """获取所有足球赛事：遍历 soccer series -> 获取 open events
        使用限流避免 429 Too Many Requests
        """
        soccer_series = await self._fetch_soccer_series()
        if not soccer_series:
            return []

        tickers = [s["ticker"] for s in soccer_series if s.get("ticker")]

        # 限流：最多 5 个并发，避免 429
        semaphore = asyncio.Semaphore(5)
        all_events: list[dict] = []

        async def fetch_with_limit(ticker: str) -> list[dict]:
            async with semaphore:
                result = await self._fetch_events_for_series(ticker)
                await asyncio.sleep(0.1)
                return result

        # 分批处理，每批 15 个，批间等待 1.5s
        batch_size = 15
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            tasks = [fetch_with_limit(t) for t in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in batch_results:
                if isinstance(res, Exception):
                    continue
                all_events.extend(res)
            if i + batch_size < len(tickers):
                await asyncio.sleep(1.5)

        results = []
        seen_tickers = set()
        for ev in all_events:
            event_ticker = ev.get("event_ticker", "")
            if event_ticker in seen_tickers:
                continue
            seen_tickers.add(event_ticker)

            title = ev.get("title", "")
            if query and query.lower() not in title.lower():
                continue

            # 提取时间：优先用 nested markets 的 close_time
            close_time = ""
            markets = ev.get("markets", [])
            if markets:
                close_time = markets[0].get("close_time", "")
            if not close_time:
                close_time = ev.get("end_date", "")

            # 收集该 event 下所有 market tickers（用于后续 order book）
            market_tickers = [m.get("ticker", "") for m in markets if m.get("ticker")]

            results.append({
                "market_id": event_ticker,
                "title": title,
                "end_date": close_time,
                "market_tickers": market_tickers,
                "category": ev.get("category", ""),
                "series_ticker": ev.get("series_ticker", ""),
            })

        print(f"[kalshi] Found {len(results)} soccer events across {len(soccer_series)} series")
        return results

    async def fetch_order_book(self, ticker: str, outcome: str = "") -> OrderBook | None:
        """获取单个 market 的 order book
        Kalshi API 返回 orderbook_fp，包含 yes_dollars 和 no_dollars
        价格为美元小数 (0.00-1.00)，size 为美元金额
        """
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/markets/{ticker}/orderbook",
                params={"depth": 50},
            )
            resp.raise_for_status()
            raw = resp.json()
            # API 返回 orderbook_fp (不是 orderbook)
            data = raw.get("orderbook_fp") or raw.get("orderbook") or {}
            bids = [
                OrderLevel(price=float(b[0]), size=float(b[1]))
                for b in data.get("yes_dollars") or data.get("yes") or []
            ]
            asks = [
                OrderLevel(price=float(a[0]), size=float(a[1]))
                for a in data.get("no_dollars") or data.get("no") or []
            ]
            # yes_dollars 按价格降序排列 (最高出价在前)
            bids.sort(key=lambda x: x.price, reverse=True)
            # no_dollars 按价格升序排列 (最低要价在前)
            asks.sort(key=lambda x: x.price)
            return OrderBook(bids=bids, asks=asks, timestamp=datetime.now(timezone.utc))
        except Exception as e:
            print(f"[kalshi] fetch_order_book({ticker}) error: {e}")
            return None

    async def fetch_event(self, event_ticker: str) -> list[MarketEvent]:
        """获取 event 下所有 markets 的详情和 order book（并发获取 orderbook）"""
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/events/{event_ticker}",
                params={"with_nested_markets": "true"},
            )
            resp.raise_for_status()
            ev = resp.json().get("event", {})
            markets = ev.get("markets", [])

            if not markets:
                return await self._fetch_single_market(event_ticker)

            # 并发获取所有 market 的 orderbook
            tickers = [m.get("ticker", "") for m in markets]
            obs = await asyncio.gather(
                *[self.fetch_order_book(t) for t in tickers],
                return_exceptions=True,
            )

            results = []
            for i, m in enumerate(markets):
                title = m.get("title", ev.get("title", ""))
                subtitle = m.get("subtitle", m.get("yes_sub_title", ""))
                display = f"{title} - {subtitle}" if subtitle else title

                ob = obs[i] if not isinstance(obs[i], Exception) else None

                last_price = m.get("last_price_dollars")
                if last_price is not None:
                    last_price = float(last_price)
                else:
                    lp_old = m.get("last_price")
                    last_price = float(lp_old) / 100 if lp_old is not None else None

                vol_24h = m.get("volume_24h_fp") or m.get("volume_24h")
                vol = m.get("volume_fp") or m.get("volume")

                results.append(MarketEvent(
                    market_id=tickers[i],
                    market_name=self.name,
                    event_title=display,
                    outcome=m.get("yes_sub_title", "Yes"),
                    order_book=ob,
                    last_price=last_price,
                    volume_24h=float(vol_24h) if vol_24h else (float(vol) if vol else None),
                ))
            return results
        except Exception as e:
            print(f"[kalshi] fetch_event({event_ticker}) error: {e}")
            return await self._fetch_single_market(event_ticker)

    async def _fetch_single_market(self, ticker: str) -> list[MarketEvent]:
        """获取单个 market 的信息"""
        try:
            resp = await self.client.get(f"{self.BASE_URL}/markets/{ticker}")
            resp.raise_for_status()
            m = resp.json().get("market", {})
            ob = await self.fetch_order_book(ticker)

            last_price = m.get("last_price")
            if last_price is not None:
                last_price = float(last_price) / 100

            return [MarketEvent(
                market_id=ticker,
                market_name=self.name,
                event_title=m.get("title", ""),
                outcome="Yes",
                order_book=ob,
                last_price=last_price,
                volume_24h=float(m.get("volume_24h", 0)) if m.get("volume_24h") else None,
            )]
        except Exception as e:
            print(f"[kalshi] _fetch_single_market({ticker}) error: {e}")
            return []
