import asyncio
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime

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
ws_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry
    registry = MarketRegistry.create_default()
    yield
    await registry.close_all()


app = FastAPI(title="Prediction Market Liquidity Comparator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST: 映射管理 ──

@app.get("/api/mappings")
async def list_mappings() -> list[EventMapping]:
    return mapping_store.list_mappings()


@app.post("/api/mappings")
async def create_mapping(display_name: str, event_time: str | None = None) -> EventMapping:
    return mapping_store.create_mapping(display_name, event_time)


@app.put("/api/mappings/{unified_id}/market")
async def add_market(unified_id: str, market_name: str, market_event_id: str):
    if market_name not in registry.list_markets():
        raise HTTPException(400, f"Unknown market: {market_name}. Available: {registry.list_markets()}")
    result = mapping_store.add_market_to_mapping(unified_id, market_name, market_event_id)
    if not result:
        raise HTTPException(404, "Mapping not found")
    return result


@app.delete("/api/mappings/{unified_id}/market/{market_name}")
async def remove_market(unified_id: str, market_name: str):
    result = mapping_store.remove_market_from_mapping(unified_id, market_name)
    if not result:
        raise HTTPException(404, "Mapping not found")
    return result


@app.delete("/api/mappings/{unified_id}")
async def delete_mapping(unified_id: str):
    if not mapping_store.delete_mapping(unified_id):
        raise HTTPException(404, "Mapping not found")
    return {"ok": True}


# ── REST: 市场管理 ──

@app.get("/api/markets")
async def list_markets():
    return {"markets": registry.list_markets()}


@app.get("/api/markets/{market_name}/search")
async def search_events(market_name: str, q: str = ""):
    adapter = registry.get(market_name)
    if not adapter:
        raise HTTPException(404, f"Market '{market_name}' not found")
    return await adapter.search_soccer_events(q)


# ── REST: 获取对比数据 ──

@app.get("/api/compare/{unified_id}")
async def compare_event(unified_id: str):
    mapping = mapping_store.get_mapping(unified_id)
    if not mapping:
        raise HTTPException(404, "Mapping not found")
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


# ── WebSocket: 实时推送 ──

@app.websocket("/ws/live/{unified_id}")
async def ws_live(websocket: WebSocket, unified_id: str):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            mapping = mapping_store.get_mapping(unified_id)
            if not mapping:
                await websocket.send_json({"error": "Mapping not found"})
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
                "timestamp": datetime.utcnow().isoformat(),
                "markets": results,
            })
            await asyncio.sleep(5)  # 每5秒刷新
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


# ── 静态文件 (前端) ──
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
