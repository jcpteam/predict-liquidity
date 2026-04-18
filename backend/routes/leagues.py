from fastapi import APIRouter
from collections import defaultdict
from datetime import datetime, timezone
import json

from db.database import async_session, DBMarketBtx, DBMarketPolyMarket
from sqlalchemy import select, delete, update, and_, func, text

router = APIRouter(prefix="/api", tags=["events"])


async def _fetch_leagues_from_table(table_name: str, sport_type: str) -> list:
    """
    从指定表查询联赛数据
    
    Args:
        table_name: 表名 (如 market_polymarket, market_btx)
        sport_type: 运动类型 (如 football, cricket)
    
    Returns:
        [(league_name, count), ...] 列表
    """
    async with async_session() as session:
        result = await session.execute(
            text(f"""
                SELECT league, COUNT(*) as count 
                FROM (
                    SELECT league 
                    FROM {table_name} 
                    WHERE sport_id = :type 
                    GROUP BY display_names, start_time
                ) m 
                GROUP BY league 
                ORDER BY league
            """),
            {"type": sport_type}
        )
        return result.all()


@router.get("/{type}/leagues")
async def list_leagues(type: str):
    """返回所有联赛（合并多平台数据，不过滤活跃状态和市场匹配）"""
    # 定义需要查询的平台表
    platform_tables = [
        "market_polymarket",
        "market_btx",
        "market_kalshi"
        # 后续可添加其他平台表
    ]
    
    # 使用字典合并各平台的联赛计数
    league_counts = defaultdict(int)
    
    # 并行查询各平台数据，相同联赛取最大计数
    for table_name in platform_tables:
        try:
            rows = await _fetch_leagues_from_table(table_name, type)
            for league_name, count in rows:
                if league_name:  # 跳过空值
                    # 如果该联赛已存在，取较大值；否则直接赋值
                    league_counts[league_name] = max(league_counts[league_name], count)
        except Exception as e:
            print(f"[leagues] Failed to fetch from {table_name}: {e}")
            continue
    
    # 转换为返回列表并过滤掉计数为0的
    return [
        {"name": name, "count": cnt, "sport": "crkt"}
        for name, cnt in sorted(league_counts.items()) 
        if cnt > 0
    ]

async def _fetch_events_from_table(table_name: str, league: str, sport_type: str) -> list:
    """
    从指定表查询联赛下的赛事数据
    
    Args:
        table_name: 表名 (如 market_polymarket, market_btx)
        league: 联赛名称
    
    Returns:
        [(display_names, start_time, ...), ...] 列表
    """
    async with async_session() as session:
        result = await session.execute(
            text(f"""
                SELECT * FROM (
                    SELECT * FROM {table_name} WHERE league = :league and sport_id = :sport_type
                ) m 
                GROUP BY display_names, start_time
                ORDER BY start_time ASC
            """),
            {"league": league, "sport_type": sport_type}
        )
        return result.fetchall()


@router.get("/events")
async def list_events_by_league(type: str, league: str):
    """返回指定联赛的所有比赛(合并多平台数据,去重后返回)
    
    Args:
        type: 运动类型 (如 football, cricket)
        league: 联赛名称
    """
    # 定义需要查询的平台表
    platform_tables = [
        "market_polymarket",
        "market_btx",
        "market_kalshi"
        # 后续可添加其他平台表
    ]

    # 使用字典存储赛事,key为(display_names, start_time)用于去重
    events_dict = {}

    # 查询各平台数据并合并
    for table_name in platform_tables:
        try:
            rows = await _fetch_events_from_table(table_name, league, type)
            for row in rows:
                # 使用 display_names 和 start_time 作为唯一键
                key = (row.display_names, row.start_time.strftime("%Y-%m-%d"))
                platform_name = table_name.replace("market_", "")

                if key not in events_dict:
                    # 首次遇到该赛事,创建新记录
                    # 判断是否活跃:start_time >= 当前时间为true
                    is_active = False
                    if row.start_time:
                        now_utc = datetime.now(timezone.utc)
                        start_utc = row.start_time
                        if start_utc.tzinfo is None:
                            start_utc = start_utc.replace(tzinfo=timezone.utc)
                        is_active = start_utc >= now_utc

                    events_dict[key] = {
                        "unified_id": '',
                        "display_name": row.display_names,
                        "start_time": row.start_time.isoformat() if row.start_time else None,
                        "end_date": row.start_time.isoformat() if row.start_time else None,
                        "event_time": row.start_time.isoformat() if row.start_time else None,
                        "league": row.league,
                        "sport_id": row.sport_id,
                        "is_active": is_active,
                        "linked_markets": [platform_name],  # 初始化平台列表
                    }
                else:
                    # 已存在,添加当前平台到列表(避免重复)
                    if platform_name not in events_dict[key]["linked_markets"]:
                        events_dict[key]["linked_markets"].append(platform_name)
        except Exception as e:
            print(f"[events] Failed to fetch from {table_name}: {e}")
            continue

    # 按开始时间排序并返回列表
    sorted_events = sorted(
        events_dict.values(),
        key=lambda x: x["start_time"] or ""
    )

    return sorted_events

from pydantic import BaseModel
from typing import Optional

class EventQueryRequest(BaseModel):
    display_name: str
    start_time: str
    sport_id: str
    league: Optional[str] = None  # 可选字段


async def _fetch_markets_from_table(table_name: str, display_name: str, start_time: str, sport_id: str) -> list:
    """
    从指定表查询赛事的所有市场数据
    
    Args:
        table_name: 表名 (如 market_polymarket, market_btx)
        display_name: 赛事名称
        start_time: 赛事开始时间
        sport_id: 运动类型
    
    Returns:
        查询结果列表
    """
    async with async_session() as session:
        result = await session.execute(
            text(f"""
                SELECT * FROM {table_name}
                WHERE display_names = :display_name
                AND date_format(start_time,'%Y-%m-%d') = :start_time
                AND sport_id = :sport_id
            """),
            {
                "display_name": display_name,
                "start_time": start_time,
                "sport_id": sport_id
            }
        )
        return result.fetchall()


@router.post("/all_market")
async def list_all_market_by_event(request: EventQueryRequest):
    """返回指定赛事的所有市场数据（合并多平台数据）"""
    # 定义需要查询的平台表
    platform_tables = [
        "market_polymarket",
        "market_btx",
        "market_kalshi"
        # 后续可添加其他平台表
    ]

    all_markets = []

    # 查询各平台数据并合并
    for table_name in platform_tables:
        try:
            rows = await _fetch_markets_from_table(
                table_name,
                request.display_name,
                request.start_time[0:10],
                request.sport_id
            )
            markets_data = []
            
            if table_name == "market_polymarket":
                # 按 market_type 收集所有 outcomes
                type_groups = defaultdict(list)
                type_market_ids_pm = {}  # market_type -> first market_id
                for row in rows:
                        market_type = row.type
                        if market_type not in type_market_ids_pm:
                            type_market_ids_pm[market_type] = row.market_id
                        runners = json.loads(row.runners) if row.runners else []
                        # neg_risk 是 bytes 类型，b'0' 表示普通市场
                        if row.neg_risk == b'0' or row.neg_risk == b'False':
                            # 普通市场：解析所有 outcome
                            outcomes = json.loads(row.outcomes) if row.outcomes else []
                            for idx in range(len(outcomes)):
                                type_groups[market_type].append({
                                    "name": outcomes[idx],
                                    "id": runners[idx] if idx < len(runners) else None
                                })
                        else:
                            # 负风险市场
                            type_groups[market_type].append({
                                "name": row.item_title,
                                "id": runners[0] if runners else None
                            })
                # 转换为 markets_data 格式
                markets_data = [
                    {"market_type": mtype, "market_id": type_market_ids_pm.get(mtype, ""), "outcomes": outcomes}
                    for mtype, outcomes in type_groups.items()
                ]
            if table_name == "market_btx":
                type_groups = defaultdict(list)
                type_market_ids = {}  # market_type -> first market_id
                for row in rows:
                    market_type = row.type
                    if market_type not in type_market_ids:
                        type_market_ids[market_type] = row.market_id
                    # runners 是数组对象，提取 id 字段
                    runners_data = json.loads(row.runners) if row.runners else []
                    runners = [item["id"] for item in runners_data]
                    title = row.display_names.split(" v ")
                    outcomes = json.loads(row.outcomes) if row.outcomes else []
                    if row.neg_risk == b'0' or row.neg_risk == b'False':
                        for idx in range(len(runners)):
                            type_groups[market_type].append({
                                "name": title[idx] if len(runners[idx]) == 14 else runners[idx],
                                "id": row.market_id
                            })
                    else:
                        type_groups[market_type].append({
                            "name": runners[0],
                            "id": row.market_id
                        })
                
                markets_data = [
                    {"market_type": mtype, "market_id": type_market_ids.get(mtype, ""), "outcomes": outcomes}
                    for mtype, outcomes in type_groups.items()
                ]
            if table_name == "market_kalshi":
                type_groups = defaultdict(list)
                type_market_ids_k = {}  # market_type -> first market_id
                for row in rows:
                    market_type = row.type
                    if market_type not in type_market_ids_k:
                        type_market_ids_k[market_type] = row.market_id
                    # runners 是数组对象，提取 id 字段
                    runners_data = json.loads(row.runners) if row.runners else []
                    runners = [item["id"] for item in runners_data]
                    title = row.display_names.split(" v ")
                    outcomes = json.loads(row.outcomes) if row.outcomes else []
                    if row.neg_risk == b'0' or row.neg_risk == b'False':
                        for idx in range(len(runners)):
                            type_groups[market_type].append({
                                "name": title[idx] if len(runners[idx]) == 14 else runners[idx],
                                "id": row.market_id
                            })
                    else:
                        type_groups[market_type].append({
                            "name": runners[0],
                            "id": row.market_id
                        })

                markets_data = [
                    {"market_type": mtype, "market_id": type_market_ids_k.get(mtype, ""), "outcomes": outcomes}
                    for mtype, outcomes in type_groups.items()
                ]
            all_markets.append({
                "platform": table_name,
                "markets": markets_data
            })
        except Exception as e:
            print(f"[events] Failed to fetch from {table_name}: {e}")
            continue

    return all_markets