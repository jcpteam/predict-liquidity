from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class OrderLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    bids: list[OrderLevel]
    asks: list[OrderLevel]
    timestamp: datetime


class MarketEvent(BaseModel):
    market_id: str          # 该市场内部的事件ID
    market_name: str        # 市场名称 (polymarket / kalshi / betfair / ...)
    event_title: str        # 事件标题
    outcome: str            # 结果选项 (e.g. "Yes", "No", "Team A Win")
    order_book: Optional[OrderBook] = None
    last_price: Optional[float] = None
    volume_24h: Optional[float] = None


class EventMapping(BaseModel):
    unified_id: str                     # 统一事件ID
    display_name: str                   # 展示名称
    sport: str = "soccer"
    event_time: Optional[datetime] = None
    mappings: dict[str, str]            # {market_name: market_event_id}


class MarketConfig(BaseModel):
    name: str
    enabled: bool = True
    api_base_url: str
    api_key: Optional[str] = None
