from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from models import EventMapping, MarketEvent
from mapping import EventMappingStore
from markets.registry import MarketRegistry
from automatch import AutoMatcher
from database import init_db, close_db

registry: MarketRegistry = None  # type: ignore
mapping_store = EventMappingStore()


async def _do_sync_polymarket():
    adapter = registry.get("polymarket")
    if not adapter:
        return {"new": 0, "updated": 0}
    events = await adapter.fetch_all_soccer_events()
    result = await mapping_store.sync_from_polymarket(events)
    print(f"[sync] Polymarket: new={result['new']}, updated={result['updated']}")
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry
    await init_db()
    registry = MarketRegistry.create_default()
    yield
    await registry.close_all()
    await close_db()


app = FastAPI(title="Prediction Market Liquidity Comparator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ── 事件列表 ──

@app.get("/api/events")
async def list_events():
    mappings = await mapping_store.list_mappings()
    result = []
    for m in mappings:
        pm = m.polymarket_data or {}
        tags = []
        for t in pm.get("tags", []):
            label = t.get("label", t.get("slug", "")) if isinstance(t, dict) else str(t)
            if label:
                tags.append(label)
        result.append({
            "unified_id": m.unified_id,
            "display_name": m.display_name,
            "event_time": m.event_time,
            "liquidity": pm.get("liquidity"),
            "volume_24hr": pm.get("volume24hr"),
            "volume": pm.get("volume"),
            "image": pm.get("icon") or pm.get("image"),
            "end_date": pm.get("endDate"),
            "market_count": len(pm.get("markets", [])),
            "linked_markets": list(m.mappings.keys()),
            "tags": tags,
        })
    return result


# ── 同步: 拉取新事件 + 清理已结束 + 自动匹配 ──

@app.post("/api/events/sync")
async def sync_events():
    sync_result = await _do_sync_polymarket()
    expired = await mapping_store.cleanup_expired()
    # 自动匹配 kalshi
    matcher = AutoMatcher(mapping_store, registry)
    match_results = await matcher.auto_match_all()
    return {
        "ok": True,
        "new": sync_result["new"],
        "updated": sync_result["updated"],
        "expired_removed": expired,
        "auto_match": match_results,
    }


# ── 映射管理 ──

@app.get("/api/events/{unified_id}/mapping")
async def get_mapping(unified_id: str):
    mapping = await mapping_store.get_mapping(unified_id)
    if not mapping:
        raise HTTPException(404, "Event not found")
    return mapping


@app.put("/api/events/{unified_id}/mapping")
async def add_market_mapping(unified_id: str, market_name: str, market_event_id: str):
    if market_name not in registry.list_markets():
        raise HTTPException(400, f"Unknown market: {market_name}")
    result = await mapping_store.add_market_mapping(unified_id, market_name, market_event_id)
    if not result:
        raise HTTPException(404, "Event not found")
    return result


@app.delete("/api/events/{unified_id}/mapping/{market_name}")
async def remove_market_mapping(unified_id: str, market_name: str):
    result = await mapping_store.remove_market_mapping(unified_id, market_name)
    if not result:
        raise HTTPException(404, "Event not found")
    return result


# ── 市场列表 & 搜索 ──

@app.get("/api/markets")
async def list_markets():
    return {"markets": registry.list_markets()}


@app.get("/api/markets/{market_name}/search")
async def search_market_events(market_name: str, q: str = ""):
    adapter = registry.get(market_name)
    if not adapter:
        raise HTTPException(404, f"Market '{market_name}' not found")
    return await adapter.search_soccer_events(q)


# ── 自动映射 ──

@app.post("/api/automatch/{market_name}")
async def auto_match_market(market_name: str):
    matcher = AutoMatcher(mapping_store, registry)
    result = await matcher.auto_match_market(market_name)
    if "error" in result and result.get("matched", -1) < 0:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/automatch")
async def auto_match_all():
    matcher = AutoMatcher(mapping_store, registry)
    results = await matcher.auto_match_all()
    return {"results": results}


# ── Order Book (按需加载, 进入详情页时调用) ──

@app.get("/api/events/{unified_id}/orderbooks")
async def get_event_orderbooks(unified_id: str):
    mapping = await mapping_store.get_mapping(unified_id)
    if not mapping:
        raise HTTPException(404, "Event not found")

    results: dict[str, list[dict]] = {}
    tasks = []
    market_names = []
    for mname, meid in mapping.mappings.items():
        adapter = registry.get(mname)
        if adapter:
            tasks.append(adapter.fetch_event(meid))
            market_names.append(mname)

    fetched = await asyncio.gather(*tasks, return_exceptions=True)
    for mname, data in zip(market_names, fetched):
        if isinstance(data, Exception):
            results[mname] = [{"error": str(data)}]
        else:
            results[mname] = [ev.model_dump(mode="json") for ev in data]

    return {
        "unified_id": mapping.unified_id,
        "display_name": mapping.display_name,
        "event_time": mapping.event_time,
        "markets": results,
    }


# ── 清理已结束事件 ──

@app.post("/api/events/cleanup")
async def cleanup_events():
    count = await mapping_store.cleanup_expired()
    return {"removed": count}


# ── 联赛列表 ──

@app.get("/api/leagues")
async def list_leagues():
    return await mapping_store.list_leagues()


# ── 静态文件 ──
for candidate in [
    Path(__file__).parent / "frontend_dist",
    Path(__file__).parent.parent / "frontend" / "dist",
]:
    if candidate.exists():
        app.mount("/", StaticFiles(directory=str(candidate), html=True), name="frontend")
        break


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
