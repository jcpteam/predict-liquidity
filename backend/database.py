"""数据库连接与 ORM 模型"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer,
    create_engine, text,
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

load_dotenv()

DB_TYPE = os.getenv("db_type", "mysql")
DB_HOST = os.getenv("db_host", "127.0.0.1")
DB_PORT = os.getenv("db_port", "3306")
DB_USER = os.getenv("db_user", "root")
DB_PASSWD = os.getenv("db_passwd", "")
DB_NAME = os.getenv("db_name", "predict_liquidity")

DATABASE_URL = (
    f"mysql+aiomysql://{DB_USER}:{DB_PASSWD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
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
    polymarket_data_json = Column(Text, nullable=True)  # full polymarket event JSON
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
        # unique constraint: one mapping per (unified_id, market_name)
        {"mysql_charset": "utf8mb4"},
    )


async def init_db():
    """创建所有表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[db] Tables initialized")


async def close_db():
    await engine.dispose()
