from __future__ import annotations

from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class OrderLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    bids: list[OrderLevel]
    asks: list[OrderLevel]
    timestamp: datetime


class MarketEvent(BaseModel):
    market_id: str
    token_id: Optional[str] = None
    market_name: str
    event_title: str
    outcome: str
    order_book: Optional[OrderBook] = None
    last_price: Optional[float] = None
    volume_24h: Optional[float] = None


class EventMapping(BaseModel):
    unified_id: str                     # = polymarket event id
    display_name: str
    sport: str = "soccer"
    event_time: Optional[datetime] = None
    mappings: dict[str, str] = {}       # {market_name: market_event_id}
    polymarket_data: Optional[dict[str, Any]] = None  # 缓存的 polymarket 事件原始数据


class MarketConfig(BaseModel):
    name: str
    enabled: bool = True
    api_base_url: str
    api_key: Optional[str] = None
