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


def _parse_end_date(pm_data: dict) -> Optional[datetime]:
    s = pm_data.get("endDate", "")
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class EventMappingStore:
    """数据库版事件映射管理"""

    # ── 同步 Polymarket 事件到数据库 ──

    async def sync_from_polymarket(self, events: list[dict]) -> dict:
        now = datetime.now(timezone.utc)
        new_count = 0
        updated_count = 0
        async with async_session() as session:
            for ev in events:
                eid = str(ev.get("id", ""))
                if not eid:
                    continue
                tags = _extract_tags(ev)
                league = _get_league_tag(tags)
                end_date = _parse_end_date(ev)

                existing = await session.get(DBEvent, eid)
                if existing:
                    existing.display_name = ev.get("title", existing.display_name)
                    existing.league = league
                    existing.end_date = end_date
                    existing.image = ev.get("icon") or ev.get("image")
                    existing.liquidity = str(ev.get("liquidity", ""))
                    existing.volume = str(ev.get("volume", ""))
                    existing.volume_24hr = str(ev.get("volume24hr", ""))
                    existing.market_count = len(ev.get("markets", []))
                    existing.tags_json = json.dumps(tags)
                    existing.polymarket_data_json = json.dumps(ev, default=str)
                    existing.is_active = True
                    existing.updated_at = now
                    updated_count += 1
                else:
                    db_ev = DBEvent(
                        unified_id=eid,
                        display_name=ev.get("title", ""),
                        league=league,
                        event_time=ev.get("startDate"),
                        end_date=end_date,
                        image=ev.get("icon") or ev.get("image"),
                        liquidity=str(ev.get("liquidity", "")),
                        volume=str(ev.get("volume", "")),
                        volume_24hr=str(ev.get("volume24hr", "")),
                        market_count=len(ev.get("markets", [])),
                        tags_json=json.dumps(tags),
                        polymarket_data_json=json.dumps(ev, default=str),
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(db_ev)
                    new_count += 1

                    # 自动添加 polymarket 自身映射
                    pm_map = DBMapping(
                        unified_id=eid,
                        market_name="polymarket",
                        market_event_id=eid,
                        created_at=now,
                    )
                    session.add(pm_map)

            await session.commit()

            # 更新联赛表
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
                select(DBEvent).where(
                    and_(DBEvent.is_active == True, DBEvent.league == league)
                )
            )).scalars().all()
            return [self._event_to_dict(ev) for ev in events]

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
