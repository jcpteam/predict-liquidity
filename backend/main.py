from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from models import EventMapping, MarketEvent
from mapping import EventMappingStore
from markets.registry import MarketRegistry


# ── Global state ──
registry: MarketRegistry = None  # type: ignore
mapping_store = EventMappingStore()


async def sync_polymarket_events():
    """从 Polymarket 拉取所有足球赛事并同步到映射表"""
    adapter = registry.get("polymarket")
    if not adapter:
        return
    events = await adapter.fetch_all_soccer_events()
    mapping_store.sync_from_polymarket(events)
    print(f"[sync] Synced {len(events)} Polymarket soccer events")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry
    registry = MarketRegistry.create_default()
    await sync_polymarket_events()
    yield
    await registry.close_all()


app = FastAPI(title="Prediction Market Liquidity Comparator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST: 事件列表（基于 Polymarket） ──

@app.get("/api/events")
async def list_events():
    """返回所有足球赛事列表（轻量，不含 order book）"""
    mappings = mapping_store.list_mappings()
    result = []
    for m in mappings:
        pm = m.polymarket_data or {}
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
        })
    return result


@app.post("/api/events/sync")
async def sync_events():
    """手动触发同步 Polymarket 事件"""
    await sync_polymarket_events()
    return {"ok": True, "count": len(mapping_store.list_mappings())}


# ── REST: 映射管理 ──

@app.get("/api/events/{unified_id}/mapping")
async def get_mapping(unified_id: str):
    mapping = mapping_store.get_mapping(unified_id)
    if not mapping:
        raise HTTPException(404, "Event not found")
    return mapping


@app.put("/api/events/{unified_id}/mapping")
async def add_market_mapping(unified_id: str, market_name: str, market_event_id: str):
    if market_name not in registry.list_markets():
        raise HTTPException(400, f"Unknown market: {market_name}")
    result = mapping_store.add_market_mapping(unified_id, market_name, market_event_id)
    if not result:
        raise HTTPException(404, "Event not found")
    return result


@app.delete("/api/events/{unified_id}/mapping/{market_name}")
async def remove_market_mapping(unified_id: str, market_name: str):
    result = mapping_store.remove_market_mapping(unified_id, market_name)
    if not result:
        raise HTTPException(404, "Event not found")
    return result


# ── REST: 市场列表 & 搜索 ──

@app.get("/api/markets")
async def list_markets():
    return {"markets": registry.list_markets()}


@app.get("/api/markets/{market_name}/search")
async def search_market_events(market_name: str, q: str = ""):
    adapter = registry.get(market_name)
    if not adapter:
        raise HTTPException(404, f"Market '{market_name}' not found")
    return await adapter.search_soccer_events(q)


# ── REST: 按需加载 Order Book 对比 ──

@app.get("/api/events/{unified_id}/orderbooks")
async def get_event_orderbooks(unified_id: str):
    """选中具体赛事时加载所有关联市场的 order book"""
    mapping = mapping_store.get_mapping(unified_id)
    if not mapping:
        raise HTTPException(404, "Event not found")

    results: dict[str, list[dict]] = {}
    tasks = []
    market_names = []

    for market_name, market_event_id in mapping.mappings.items():
        adapter = registry.get(market_name)
        if adapter:
            tasks.append(adapter.fetch_event(market_event_id))
            market_names.append(market_name)

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


# ── WebSocket: 实时推送选中事件的 order book ──

@app.websocket("/ws/live/{unified_id}")
async def ws_live(websocket: WebSocket, unified_id: str):
    await websocket.accept()
    try:
        while True:
            mapping = mapping_store.get_mapping(unified_id)
            if not mapping:
                await websocket.send_json({"error": "Event not found"})
                break

            results = {}
            tasks = []
            market_names = []
            for market_name, market_event_id in mapping.mappings.items():
                adapter = registry.get(market_name)
                if adapter:
                    tasks.append(adapter.fetch_event(market_event_id))
                    market_names.append(market_name)

            fetched = await asyncio.gather(*tasks, return_exceptions=True)
            for mname, data in zip(market_names, fetched):
                if isinstance(data, Exception):
                    results[mname] = [{"error": str(data)}]
                else:
                    results[mname] = [ev.model_dump(mode="json") for ev in data]

            await websocket.send_json({
                "unified_id": unified_id,
                "display_name": mapping.display_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "markets": results,
            })
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass


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
