"""数据库连接与 ORM 模型"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
from urllib.parse import quote as _url_quote

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer, BigInteger,
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


class DBMarketBtx(Base):
    """BTX 市场数据主表"""
    __tablename__ = "market_btx"

    market_id = Column(String(64), primary_key=True, nullable=False)
    event_id = Column(String(64), nullable=False, index=True)
    display_names = Column(String(512), nullable=False, default="")
    league = Column(String(255), nullable=False, default="")
    sport_id = Column(String(64), nullable=False, default="")
    market_type = Column(String(64), nullable=False, default="")
    status = Column(Integer, nullable=False, default=0)
    start_time = Column(DateTime, nullable=True)
    runners = Column(String(200), nullable=True)
    outcomes = Column(String(100), nullable=True)
    item_title = Column(String(255), nullable=True)
    neg_risk = Column(Text, nullable=True)  # BLOB 映射为 Text
    type = Column(String(128), nullable=False, default="")
    update_time = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = ({"mysql_charset": "utf8mb4"},)


class DBMarketPolyMarket(Base):
    """PloyMarket 市场数据主表"""
    __tablename__ = "market_polymarket"

    market_id = Column(String(64), primary_key=True, nullable=False)
    event_id = Column(String(64), nullable=False, index=True)
    display_names = Column(String(512), nullable=False, default="")
    league = Column(String(255), nullable=False, default="")
    sport_id = Column(String(64), nullable=False, default="")
    market_type = Column(String(64), nullable=False, default="")
    status = Column(Integer, nullable=False, default=0)
    start_time = Column(DateTime, nullable=True)
    runners = Column(String(200), nullable=True)
    outcomes = Column(String(100), nullable=True)
    item_title = Column(String(255), nullable=True)
    neg_risk = Column(Text, nullable=True)  # BLOB 映射为 Text
    type = Column(String(128), nullable=False, default="")
    update_time = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

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
