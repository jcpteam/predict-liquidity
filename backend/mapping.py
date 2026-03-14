"""事件映射管理 - 基于 MySQL 数据库存储"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, delete, update, and_, func
from database import async_session, DBEvent, DBMapping, DBLeague
from models import EventMapping


# ── 通用 tag 过滤 (与前端保持一致) ──
GENERIC_TAGS = {
    'Soccer','Sports','Games','Goals','Awards','Culture',
    'Celebrities','World','Parlays','Geopolitics','Politics',
    'Hide From New','yellow card','red card','red cards',
    'assists','assist','goal','goal contributions','goals',
    'clean sheet','clean sheets','goalie','goalkeeper','keeper',
    'card','golden boot','most valuable player','mvp',
    'man of the match','player of the match','motm','potm',
    'transfer','sea',
}
TAG_NORMALIZE = {
    'Premier League':'EPL','Champions League':'UCL',
    'Europa League':'UEL',"Women's Champions League":'UWCL',
    'UEFA Europa League':'UEL','UEFA Conference League':'UECL',
    'Europa Conference League':'UECL','Carabao Cup':'EFL Cup',
}


def _get_league_tag(tags: list[str]) -> str:
    for t in tags:
        if t in GENERIC_TAGS:
            continue
        if t and t[0].islower() and ' League' not in t and ' Cup' not in t:
            continue
        return TAG_NORMALIZE.get(t, t)
    return 'Other'


def _extract_tags(pm_data: dict) -> list[str]:
    tags = []
    for t in pm_data.get("tags", []):
        label = t.get("label", t.get("slug", "")) if isinstance(t, dict) else str(t)
        if label:
            tags.append(label)
    return tags


def _parse_datetime(val) -> Optional[datetime]:
    """安全解析各种格式的日期时间字符串"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    return None


def _parse_end_date(pm_data: dict) -> Optional[datetime]:
    return _parse_datetime(pm_data.get("endDate", ""))


class EventMappingStore:
    """数据库版事件映射管理"""

    # ── 同步 Polymarket 事件到数据库 ──

    async def sync_from_polymarket(self, events: list[dict]) -> dict:
        """使用 raw SQL 批量 INSERT ... ON DUPLICATE KEY UPDATE，大幅减少网络往返"""
        now = datetime.now(timezone.utc)

        # 先查出已有的 unified_id 用于统计 new vs updated
        async with async_session() as session:
            existing_rows = (await session.execute(
                select(DBEvent.unified_id)
            )).scalars().all()
        existing_ids = set(existing_rows)

        new_count = 0
        updated_count = 0

        # 分批处理，每批 200 条，用 raw SQL 批量 upsert
        batch_size = 200
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            event_rows = []
            mapping_rows = []

            for ev in batch:
                eid = str(ev.get("id", ""))
                if not eid:
                    continue
                tags = _extract_tags(ev)
                league = _get_league_tag(tags)
                end_date = _parse_end_date(ev)
                pm_json = json.dumps(ev, default=str)

                is_new = eid not in existing_ids
                if is_new:
                    new_count += 1
                    existing_ids.add(eid)
                else:
                    updated_count += 1

                event_rows.append({
                    "unified_id": eid,
                    "display_name": ev.get("title", "")[:500],
                    "sport": "soccer",
                    "league": league,
                    "event_time": _parse_datetime(ev.get("startDate")),
                    "end_date": end_date,
                    "is_active": True,
                    "image": (ev.get("icon") or ev.get("image") or "")[:1000],
                    "liquidity": str(ev.get("liquidity", "")),
                    "volume": str(ev.get("volume", "")),
                    "volume_24hr": str(ev.get("volume24hr", "")),
                    "market_count": len(ev.get("markets", [])),
                    "tags_json": json.dumps(tags),
                    "polymarket_data_json": pm_json,
                    "created_at": now,
                    "updated_at": now,
                })

                if is_new:
                    mapping_rows.append({
                        "unified_id": eid,
                        "market_name": "polymarket",
                        "market_event_id": eid,
                        "created_at": now,
                    })

            if not event_rows:
                continue

            async with async_session() as session:
                # Bulk upsert events using INSERT ... ON DUPLICATE KEY UPDATE
                from sqlalchemy.dialects.mysql import insert as mysql_insert
                stmt = mysql_insert(DBEvent).values(event_rows)
                stmt = stmt.on_duplicate_key_update(
                    display_name=stmt.inserted.display_name,
                    league=stmt.inserted.league,
                    end_date=stmt.inserted.end_date,
                    image=stmt.inserted.image,
                    liquidity=stmt.inserted.liquidity,
                    volume=stmt.inserted.volume,
                    volume_24hr=stmt.inserted.volume_24hr,
                    market_count=stmt.inserted.market_count,
                    tags_json=stmt.inserted.tags_json,
                    polymarket_data_json=stmt.inserted.polymarket_data_json,
                    is_active=True,
                    updated_at=stmt.inserted.updated_at,
                )
                await session.execute(stmt)

                # Bulk insert new mappings (ignore duplicates)
                if mapping_rows:
                    m_stmt = mysql_insert(DBMapping).values(mapping_rows)
                    m_stmt = m_stmt.on_duplicate_key_update(
                        market_event_id=m_stmt.inserted.market_event_id,
                    )
                    await session.execute(m_stmt)

                await session.commit()
            print(f"  [sync] batch {i//batch_size+1}: {len(event_rows)} events")

        # 更新联赛表
        async with async_session() as session:
            await self._refresh_leagues(session)
            await session.commit()

        return {"new": new_count, "updated": updated_count}

    async def _refresh_leagues(self, session: AsyncSession):
        """根据 events 表重建 leagues 表"""
        rows = (await session.execute(
            select(DBEvent.league, func.count(DBEvent.unified_id))
            .where(DBEvent.is_active == True)
            .group_by(DBEvent.league)
        )).all()
        # 清空再插入
        await session.execute(delete(DBLeague))
        for name, cnt in rows:
            session.add(DBLeague(
                name=name, display_name=name, event_count=cnt,
                updated_at=datetime.now(timezone.utc),
            ))

    # ── 清理已结束事件 ──

    async def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        async with async_session() as session:
            result = await session.execute(
                update(DBEvent)
                .where(and_(DBEvent.end_date < now, DBEvent.is_active == True))
                .values(is_active=False)
            )
            await session.commit()
            count = result.rowcount
        return count

    # ── 查询接口 ──

    async def list_mappings(self) -> list[EventMapping]:
        async with async_session() as session:
            events = (await session.execute(
                select(DBEvent).where(DBEvent.is_active == True)
            )).scalars().all()

            result = []
            for ev in events:
                maps = (await session.execute(
                    select(DBMapping).where(DBMapping.unified_id == ev.unified_id)
                )).scalars().all()
                mappings = {m.market_name: m.market_event_id for m in maps}

                pm_data = None
                if ev.polymarket_data_json:
                    try:
                        pm_data = json.loads(ev.polymarket_data_json)
                    except (json.JSONDecodeError, TypeError):
                        pass

                result.append(EventMapping(
                    unified_id=ev.unified_id,
                    display_name=ev.display_name,
                    sport=ev.sport,
                    event_time=ev.event_time,
                    mappings=mappings,
                    polymarket_data=pm_data,
                ))
            return result

    async def get_mapping(self, unified_id: str) -> Optional[EventMapping]:
        async with async_session() as session:
            ev = await session.get(DBEvent, unified_id)
            if not ev or not ev.is_active:
                return None
            maps = (await session.execute(
                select(DBMapping).where(DBMapping.unified_id == unified_id)
            )).scalars().all()
            mappings = {m.market_name: m.market_event_id for m in maps}
            pm_data = None
            if ev.polymarket_data_json:
                try:
                    pm_data = json.loads(ev.polymarket_data_json)
                except (json.JSONDecodeError, TypeError):
                    pass
            return EventMapping(
                unified_id=ev.unified_id,
                display_name=ev.display_name,
                sport=ev.sport,
                event_time=ev.event_time,
                mappings=mappings,
                polymarket_data=pm_data,
            )

    async def add_market_mapping(self, unified_id: str, market_name: str,
                                  market_event_id: str) -> Optional[EventMapping]:
        async with async_session() as session:
            ev = await session.get(DBEvent, unified_id)
            if not ev:
                return None
            # upsert: delete old then insert
            await session.execute(
                delete(DBMapping).where(and_(
                    DBMapping.unified_id == unified_id,
                    DBMapping.market_name == market_name,
                ))
            )
            session.add(DBMapping(
                unified_id=unified_id,
                market_name=market_name,
                market_event_id=market_event_id,
            ))
            await session.commit()
        return await self.get_mapping(unified_id)

    async def remove_market_mapping(self, unified_id: str,
                                     market_name: str) -> Optional[EventMapping]:
        if market_name == "polymarket":
            return await self.get_mapping(unified_id)
        async with async_session() as session:
            await session.execute(
                delete(DBMapping).where(and_(
                    DBMapping.unified_id == unified_id,
                    DBMapping.market_name == market_name,
                ))
            )
            await session.commit()
        return await self.get_mapping(unified_id)

    async def list_leagues(self) -> list[dict]:
        async with async_session() as session:
            rows = (await session.execute(
                select(DBLeague).order_by(DBLeague.event_count.desc())
            )).scalars().all()
            return [{"name": r.name, "count": r.event_count} for r in rows]

    async def list_events_by_league(self, league: str) -> list[dict]:
        async with async_session() as session:
            events = (await session.execute(
                select(
                    DBEvent.unified_id, DBEvent.display_name, DBEvent.event_time,
                    DBEvent.end_date, DBEvent.league, DBEvent.liquidity,
                    DBEvent.volume_24hr, DBEvent.volume, DBEvent.image,
                    DBEvent.market_count, DBEvent.tags_json,
                ).where(
                    and_(DBEvent.is_active == True, DBEvent.league == league)
                )
            )).all()

            if not events:
                return []

            # 批量查出这些事件的 mappings
            eids = [e.unified_id for e in events]
            maps = (await session.execute(
                select(DBMapping.unified_id, DBMapping.market_name)
                .where(DBMapping.unified_id.in_(eids))
            )).all()

            # 按 unified_id 分组
            mapping_dict: dict[str, list[str]] = {}
            for uid, mname in maps:
                mapping_dict.setdefault(uid, []).append(mname)

            result = []
            for ev in events:
                tags = []
                if ev.tags_json:
                    try:
                        tags = json.loads(ev.tags_json)
                    except (json.JSONDecodeError, TypeError):
                        pass
                result.append({
                    "unified_id": ev.unified_id,
                    "display_name": ev.display_name,
                    "event_time": ev.event_time.isoformat() if ev.event_time else None,
                    "end_date": ev.end_date.isoformat() if ev.end_date else None,
                    "league": ev.league,
                    "liquidity": ev.liquidity,
                    "volume_24hr": ev.volume_24hr,
                    "volume": ev.volume,
                    "image": ev.image,
                    "market_count": ev.market_count,
                    "tags": tags,
                    "linked_markets": mapping_dict.get(ev.unified_id, []),
                })
            return result

    def _event_to_dict(self, ev: DBEvent) -> dict:
        tags = []
        if ev.tags_json:
            try:
                tags = json.loads(ev.tags_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "unified_id": ev.unified_id,
            "display_name": ev.display_name,
            "event_time": ev.event_time.isoformat() if ev.event_time else None,
            "end_date": ev.end_date.isoformat() if ev.end_date else None,
            "league": ev.league,
            "liquidity": ev.liquidity,
            "volume_24hr": ev.volume_24hr,
            "volume": ev.volume,
            "image": ev.image,
            "market_count": ev.market_count,
            "tags": tags,
            "is_active": ev.is_active,
        }
