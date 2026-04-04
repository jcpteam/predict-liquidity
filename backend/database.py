"""数据库连接与 ORM 模型"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
from urllib.parse import quote as _url_quote

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer,
    UniqueConstraint, create_engine, text,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase


def _load_env_file():
    """手动解析 .env 文件，不依赖 python-dotenv"""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


_load_env_file()

DB_TYPE = os.getenv("db_type", "mysql")
DB_HOST = os.getenv("db_host", "127.0.0.1")
DB_PORT = os.getenv("db_port", "3306")
DB_USER = os.getenv("db_user", "root")
DB_PASSWD = os.getenv("db_passwd", "")
DB_NAME = os.getenv("db_name", "predict_liquidity")

DATABASE_URL = (
    f"mysql+aiomysql://{DB_USER}:{_url_quote(DB_PASSWD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)

engine = create_async_engine(
    DATABASE_URL, echo=False, pool_size=5, max_overflow=10,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 30},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class DBLeague(Base):
    """联赛/赛事分组"""
    __tablename__ = "leagues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    display_name = Column(String(200), nullable=False)
    event_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DBEvent(Base):
    """赛事事件 (以 polymarket event 为基础)"""
    __tablename__ = "events"

    unified_id = Column(String(100), primary_key=True)
    display_name = Column(String(500), nullable=False)
    sport = Column(String(50), default="soccer")
    league = Column(String(200), default="Other", index=True)
    event_time = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    image = Column(String(1000), nullable=True)
    liquidity = Column(String(50), nullable=True)
    volume = Column(String(50), nullable=True)
    volume_24hr = Column(String(50), nullable=True)
    market_count = Column(Integer, default=0)
    tags_json = Column(Text, nullable=True)  # JSON array of tag strings
    polymarket_data_json = Column(LONGTEXT, nullable=True)  # full polymarket event JSON
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class DBMapping(Base):
    """跨市场映射"""
    __tablename__ = "market_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    unified_id = Column(String(100), nullable=False, index=True)
    market_name = Column(String(100), nullable=False)
    market_event_id = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("unified_id", "market_name", name="uq_mapping_event_market"),
        {"mysql_charset": "utf8mb4"},
    )


class DBBtxMarket(Base):
    """BTX 子市场（一个 fixture 有多个 market type）"""
    __tablename__ = "btx_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(100), nullable=False, index=True)  # = events.unified_id
    btx_market_id = Column(String(100), nullable=False, unique=True)
    market_type = Column(String(200), nullable=False)
    display_name = Column(String(500), nullable=True)
    betfair_market_id = Column(String(100), nullable=True)
    runners_json = Column(Text, nullable=True)  # JSON: [{"id":"xxx","name":"Team A"}, ...]
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = ({"mysql_charset": "utf8mb4"},)


async def init_db():
    """测试数据库连接（表已通过 init_sync.py 创建）"""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        print("[db] Connection OK")
    except Exception as e:
        print(f"[db] Connection failed: {e}, will retry on first request")


async def close_db():
    await engine.dispose()
