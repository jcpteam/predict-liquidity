from __future__ import annotations

from abc import ABC, abstractmethod
from models import OrderBook, MarketEvent
import httpx


class BaseMarketAdapter(ABC):
    """所有预测市场适配器的基类"""

    name: str = "base"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=60.0)

    @abstractmethod
    async def fetch_order_book(self, market_id: str, outcome: str) -> OrderBook | None:
        """获取指定事件/结果的 order book"""
        ...

    @abstractmethod
    async def fetch_event(self, market_id: str) -> list[MarketEvent]:
        """获取事件详情，返回该事件下所有 outcome 的 MarketEvent"""
        ...

    @abstractmethod
    async def search_soccer_events(self, query: str = "") -> list[dict]:
        """搜索足球相关事件，返回简要列表供映射使用"""
        ...

    async def close(self):
        await self.client.aclose()
