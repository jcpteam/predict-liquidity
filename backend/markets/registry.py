from __future__ import annotations

from .base import BaseMarketAdapter
from .polymarket import PolymarketAdapter
from .kalshi import KalshiAdapter
from .betfair import BetfairAdapter
from .btx import BTXAdapter


class MarketRegistry:
    """市场适配器注册中心，支持动态添加新市场"""

    def __init__(self):
        self._adapters: dict[str, BaseMarketAdapter] = {}

    def register(self, adapter: BaseMarketAdapter):
        self._adapters[adapter.name] = adapter

    def unregister(self, name: str):
        self._adapters.pop(name, None)

    def get(self, name: str) -> BaseMarketAdapter | None:
        return self._adapters.get(name)

    def list_markets(self) -> list[str]:
        return list(self._adapters.keys())

    def all(self) -> dict[str, BaseMarketAdapter]:
        return dict(self._adapters)

    async def close_all(self):
        for adapter in self._adapters.values():
            await adapter.close()

    @classmethod
    def create_default(cls, configs: dict | None = None) -> "MarketRegistry":
        """创建包含默认市场的注册中心"""
        registry = cls()
        configs = configs or {}
        registry.register(PolymarketAdapter(api_key=configs.get("polymarket", {}).get("api_key")))
        registry.register(KalshiAdapter(api_key=configs.get("kalshi", {}).get("api_key")))
        import os
        betfair_key = configs.get("betfair", {}).get("api_key") or os.getenv("BETFAIR_APP_KEY", "")
        registry.register(BetfairAdapter(api_key=betfair_key))
        registry.register(BTXAdapter())
        return registry
