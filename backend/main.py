from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    # 清理已结束事件
    expired = await mapping_store.cleanup_expired()
    print(f"[sync] Polymarket: new={result['new']}, updated={result['updated']}, expired={expired}")
    return result


async def _background_sync_loop():
    """后台定时同步：每 6 小时自动拉取新事件 + 清理已结束事件"""
    import os
    interval = int(os.getenv("SYNC_INTERVAL_HOURS", "6")) * 3600
    while True:
        await asyncio.sleep(interval)
        try:
            print(f"[auto-sync] 开始定时同步...")
            await _do_sync_polymarket()
            print(f"[auto-sync] 完成")
        except Exception as e:
            print(f"[auto-sync] 失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry
    await init_db()
    registry = MarketRegistry.create_default()
    # 启动后台定时同步
    sync_task = asyncio.create_task(_background_sync_loop())
    yield
    sync_task.cancel()
    await registry.close_all()
    await close_db()


app = FastAPI(title="Prediction Market Liquidity Comparator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ── 事件列表 (从数据库加载) ──

@app.get("/api/leagues")
async def list_leagues():
    return await mapping_store.list_leagues()


@app.get("/api/leagues/{league}/events")
async def list_league_events(league: str):
    return await mapping_store.list_events_by_league(league)


# ── 同步: 拉取新事件 + 清理已结束 + 自动匹配 ──

@app.post("/api/events/sync")
async def sync_events():
    sync_result = await _do_sync_polymarket()
    expired = await mapping_store.cleanup_expired()
    # 自动匹配 kalshi + betfair
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
async def get_event_orderbooks(unified_id: str, btx_market_id: str = None):
    mapping = await mapping_store.get_mapping(unified_id)
    if not mapping:
        raise HTTPException(404, "Event not found")

    results: dict[str, list[dict]] = {}
    tasks = []
    market_names = []

    for mname, meid in mapping.mappings.items():
        adapter = registry.get(mname)
        if not adapter:
            continue
        if mname == "btx" and btx_market_id:
            # Use specific BTX market ID instead of default
            tasks.append(adapter.fetch_event(btx_market_id))
        elif mname == "betfair" and btx_market_id:
            # Look up corresponding Betfair market ID from DB
            from database import async_session as _as, DBBtxMarket
            from sqlalchemy import select as _sel
            async with _as() as session:
                row = (await session.execute(
                    _sel(DBBtxMarket.betfair_market_id).where(DBBtxMarket.btx_market_id == btx_market_id)
                )).scalar()
            if row:
                tasks.append(adapter.fetch_event(row))
            else:
                tasks.append(adapter.fetch_event(meid))
        else:
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
        "btx_market_id": btx_market_id,
        "markets": results,
    }


@app.get("/api/events/{unified_id}/all-markets")
async def get_all_btx_markets(unified_id: str):
    """获取某个 fixture 的所有 BTX market types + 其他平台对应数据
    从 DB 读取 BTX market 结构（不需要实时 gRPC），其他平台实时获取
    """
    mapping = await mapping_store.get_mapping(unified_id)
    if not mapping:
        raise HTTPException(404, "Event not found")

    if "btx" not in mapping.mappings:
        return await get_event_orderbooks(unified_id)

    if "kalshi" in mapping.mappings:
        kalshi_id = mapping.mappings.get("kalshi", "")
        if kalshi_id and "KXEPLGAME" not in kalshi_id:
              # 将 KXEPL1H 替换为 KXEPLGAME
           corrected_id = kalshi_id.replace("KXEPL1H", "KXEPLGAME")
           mapping.mappings["kalshi"] = corrected_id

    # Read BTX markets from DB
    from database import async_session, DBBtxMarket
    from sqlalchemy import select
    import json as _json

    async with async_session() as session:
        rows = (await session.execute(
            select(DBBtxMarket).where(DBBtxMarket.fixture_id == unified_id)
        )).scalars().all()

    print(f"[all-markets] {unified_id}: {len(rows)} btx_markets from DB")

    if not rows:
        return await get_event_orderbooks(unified_id)

    btx_market_groups = []
    btx_to_betfair = {}
    btx_market_id_to_idx = {}  # btx_market_id -> index in btx_market_groups
    for row in rows:
        runners = []
        if row.runners_json:
            try:
                runners = _json.loads(row.runners_json)
            except:
                pass
        mtype = row.market_type or ""
        idx = len(btx_market_groups)
        btx_market_groups.append({
            "market_id": row.btx_market_id,
            "market_type": mtype,
            "market_type_display": mtype.replace("FOOTBALL_FULL_TIME_", "").replace("_", " ").title(),
            "display_name": row.display_name or "",
            "outcomes": [{"outcome": r.get("name", r.get("id", "")), "runner_id": r.get("id", "")}
                         for r in runners],
            "liquidity": 0,
        })
        btx_market_id_to_idx[row.btx_market_id] = idx
        if row.betfair_market_id:
            btx_to_betfair[row.btx_market_id] = row.betfair_market_id

    # Fetch BTX real-time prices for ALL markets of this fixture
    btx_adapter = registry.get("btx")
    if btx_adapter and "btx" in mapping.mappings:
        try:
            await btx_adapter._load_runner_names()
            # Open one stream for all market types, get price snapshot
            stream = await btx_adapter.stream_market_data(stream_prices=True)
            if stream:
                all_btx_ids = set(btx_market_id_to_idx.keys())
                import time as _time
                t0 = _time.time()
                async for msg in stream:
                    if _time.time() - t0 > 30:
                        break
                    if msg.prices and msg.prices.market_prices:
                        parsed = btx_adapter.parse_price_message(msg.prices)
                        for mid, events in parsed.items():
                            if mid in all_btx_ids:
                                idx = btx_market_id_to_idx[mid]
                                has_data = any(len(e.order_book.bids) > 0 or len(e.order_book.asks) > 0 for e in events)
                                if has_data:
                                    btx_market_groups[idx]["outcomes"] = [ev.model_dump(mode="json") for ev in events]
                                    btx_market_groups[idx]["liquidity"] = round(sum(
                                        sum(b.size for b in ev.order_book.bids) + sum(a.size for a in ev.order_book.asks)
                                        for ev in events if ev.order_book
                                    ), 2)
                                    all_btx_ids.discard(mid)
                        # Got at least some data, break after first price message
                        if len(all_btx_ids) < len(btx_market_id_to_idx):
                            break
                stream.cancel()
                filled = len(btx_market_id_to_idx) - len(all_btx_ids)
                print(f"[all-markets] BTX prices: {filled}/{len(btx_market_id_to_idx)} markets filled")
        except Exception as e:
            print(f"[all-markets] BTX price fetch error: {e}")

    # Fetch other platforms' data (Betfair per-market, others single)
    other_markets = {}
    betfair_per_btx = {}
    betfair_adapter = registry.get("betfair")

    tasks = []
    task_names = []
    for mname, meid in mapping.mappings.items():
        if mname == "btx":
            continue
        if mname == "betfair":
            if betfair_adapter:
                # Fetch all Betfair markets in parallel
                for btx_mid, bf_mid in btx_to_betfair.items():
                    tasks.append(betfair_adapter.fetch_event(bf_mid))
                    task_names.append(("betfair_per", btx_mid))
            continue
        adapter = registry.get(mname)
        if adapter:
            tasks.append(adapter.fetch_event(meid))
            task_names.append(("other", mname))

    fetched = await asyncio.gather(*tasks, return_exceptions=True)
    for (kind, key), data in zip(task_names, fetched):
        if isinstance(data, Exception):
            if kind == "other":
                other_markets[key] = [{"error": str(data)}]
            print(f"[all-markets] {kind}/{key} error: {data}")
        else:
            evts = [ev.model_dump(mode="json") for ev in data]
            if kind == "betfair_per":
                betfair_per_btx[key] = evts
                # Also put in other_markets for fallback
                if "betfair" not in other_markets:
                    other_markets["betfair"] = evts
            else:
                other_markets[key] = evts

    if "kalshi" in mapping.mappings:
        kalsh_markets = []
        kalsh_markets.append({
            "market_type": "FOOTBALL_FULL_TIME_MATCH_ODDS",
            "market_type_display": "Match Odds",
            "display_name": "Match Odds",
            "outcomes": other_markets["kalshi"],
            "liquidity": 0,
        })
        other_markets["kalshi_markets"] = kalsh_markets

    # Fetch Polymarket child events and group by market_type (like BTX)
    if "polymarket" in mapping.mappings:
        pm_event_id = mapping.mappings["polymarket"]
        pm_adapter = registry.get("polymarket")
        if pm_adapter:
            try:
                from database import async_session, DBEvent
                from sqlalchemy import select

                # Query child events where parent_eventid = pm_event_id
                async with async_session() as session:
                    child_rows = (await session.execute(
                        select(DBEvent).where(DBEvent.parent_eventid == int(pm_event_id))
                    )).scalars().all()

                # Group child events by market_type (extracted from display_name after ' - ')
                # Structure: {market_type: {conditionId: {line, groupItemTitle, outcomes: []}}}
                pm_market_groups = {}  # market_type -> {conditionId: market_info}
                pm_market_liquidity = {}  # market_type -> liquidity

                if child_rows:
                    # Fetch orderbook for each child event
                    child_tasks = []
                    child_display_names = []
                    child_pm_data_list = []
                    for child in child_rows:
                        child_tasks.append(pm_adapter.fetch_event(child.unified_id))
                        # Extract market type from display_name
                        display_name = child.display_name or ""
                        if " - " in display_name:
                            market_type = display_name.split(" - ")[-1].strip()
                        else:
                            market_type = "Unknown"
                        child_display_names.append(market_type)
                        pm_market_liquidity[market_type] = child.liquidity
                        child_pm_data_list.append(child.polymarket_data_json)

                    if child_tasks:
                        child_fetched = await asyncio.gather(*child_tasks, return_exceptions=True)
                        for market_type, child_data, pm_json_str in zip(child_display_names, child_fetched, child_pm_data_list):
                            if isinstance(child_data, Exception):
                                print(f"[all-markets] Failed to fetch child: {child_data}")
                                continue

                            # Parse polymarket_data_json to build market mapping
                            token_to_market = {}
                            if pm_json_str:
                                try:
                                    import json as _json
                                    pm_json_data = _json.loads(pm_json_str)
                                    for mkt in pm_json_data.get("markets", []):
                                        condition_id = mkt.get("conditionId", "")
                                        line = mkt.get("line")
                                        group_item_title = mkt.get("groupItemTitle", "")
                                        clob_token_ids = mkt.get("clobTokenIds", "[]")
                                        if isinstance(clob_token_ids, str):
                                            clob_token_ids = _json.loads(clob_token_ids)
                                        for tid in clob_token_ids:
                                            token_to_market[tid] = {
                                                "condition_id": condition_id,
                                                "line": line,
                                                "group_item_title": group_item_title,
                                            }
                                except Exception as e:
                                    print(f"[all-markets] Failed to parse pm_data: {e}")

                            # Initialize market_type in pm_market_groups
                            if market_type not in pm_market_groups:
                                pm_market_groups[market_type] = {}

                            # Group outcomes by conditionId
                            for ev in child_data:
                                ev_dict = ev.model_dump(mode="json")
                                token_id = ev_dict.get("token_id", "")
                                if token_id in token_to_market:
                                    mkt_info = token_to_market[token_id]
                                    cond_id = mkt_info["condition_id"]
                                    if cond_id not in pm_market_groups[market_type]:
                                        pm_market_groups[market_type][cond_id] = {
                                            "line": mkt_info["line"],
                                            "group_item_title": mkt_info["group_item_title"],
                                            "outcomes": []
                                        }
                                    pm_market_groups[market_type][cond_id]["outcomes"].append(ev_dict)

                # Reorganize polymarket data to match BTX format
                # Build polymarket_markets list: group by market_type, display_name = market_type
                # Each item: {market_type, market_type_display, display_name, outcomes, liquidity}
                polymarket_markets = []
                for market_type, markets_by_cond in pm_market_groups.items():
                    if not markets_by_cond:
                        continue
                    # Get liquidity for this market_type
                    liquidity = pm_market_liquidity.get(market_type, "0") or "0"
                    liquidity_val = float(liquidity) if liquidity.replace(".", "").replace("-", "").isdigit() else 0
                    btx_type = _map_pm_type_to_btx(market_type)

                    # Merge all outcomes from all conditionIds into one entry per market_type
                    all_outcomes = []
                    for cond_id, info in markets_by_cond.items():
                        all_outcomes.extend(info.get("outcomes", []))

                    polymarket_markets.append({
                        "market_type": btx_type,
                        "market_type_display": market_type,
                        "display_name": market_type,
                        "outcomes": all_outcomes,
                        "liquidity": liquidity_val,
                    })

                # Add Match Odds from other_markets["polymarket"] if not already in pm_market_groups
                if "Match Odds" not in pm_market_groups and "polymarket" in other_markets:
                    if isinstance(other_markets["polymarket"], list) and other_markets["polymarket"]:
                        polymarket_markets.insert(0, {
                            "market_type": "FOOTBALL_FULL_TIME_MATCH_ODDS",
                            "market_type_display": "Match Odds",
                            "display_name": "Match Odds",
                            "outcomes": other_markets["polymarket"],
                            "liquidity": 0,
                        })

                # Replace other_markets["polymarket"] with grouped structure
                other_markets["polymarket_markets"] = polymarket_markets
                print(f"[all-markets] Polymarket grouped into {len(polymarket_markets)} market types")
            except Exception as e:
                print(f"[all-markets] Failed to fetch Polymarket child events: {e}")
                import traceback; traceback.print_exc()


    types_count = {}
    for g in btx_market_groups:
        t = g.get("market_type", "?")
        types_count[t] = types_count.get(t, 0) + 1
    print(f"[all-markets] Returning {len(btx_market_groups)} groups: {types_count}")

    return {
        "unified_id": mapping.unified_id,
        "display_name": mapping.display_name,
        "event_time": mapping.event_time,
        "btx_markets": btx_market_groups,
        "other_markets": other_markets,
        "betfair_per_btx": betfair_per_btx,
    }


# ── Polymarket 类型映射 ──

def _map_pm_type_to_btx(pm_type: str) -> str:
    """Map Polymarket display type to BTX market type format"""
    type_mapping = {
        "Match Odds": "FOOTBALL_FULL_TIME_MATCH_ODDS",
        "Correct Score": "FOOTBALL_FULL_TIME_CORRECT_SCORE",
        "Over/Under": "FOOTBALL_FULL_TIME_TOTAL_GOALS_OVER_UNDER",
        "Asian Handicap": "FOOTBALL_FULL_TIME_ASIAN_HANDICAP",
        "First Half Match Odds": "FOOTBALL_FIRST_HALF_MATCH_ODDS",
        "Player Props": "PLAYER_PROPS",
        "Corners": "CORNERS",
        "Cards": "CARDS",
    }
    return type_mapping.get(pm_type, pm_type.upper().replace(" ", "_").replace("/", "_"))


# ── 清理已结束事件 ──

@app.post("/api/events/cleanup")
async def cleanup_events():
    count = await mapping_store.cleanup_expired()
    return {"removed": count}


# ── WebSocket 实时 Order Book ──

@app.websocket("/ws/orderbooks/{unified_id}")
async def ws_orderbooks(websocket: WebSocket, unified_id: str, btx_market_id: str = None):
    """WebSocket 实时推送 orderbook 数据
    1. 连接后立即发送初始 orderbook 快照
    2. Polymarket: 通过 WebSocket 订阅实时更新
    3. Kalshi: 每 5 秒轮询更新（其 WS 需要 API key 认证）
    """
    await websocket.accept()

    mapping = await mapping_store.get_mapping(unified_id)
    if not mapping:
        await websocket.send_json({"error": "Event not found"})
        await websocket.close()
        return

    # 发送初始快照
    try:
        initial = await _fetch_all_orderbooks(mapping, btx_market_id)
        await websocket.send_json({
            "type": "snapshot",
            "unified_id": unified_id,
            "display_name": mapping.display_name,
            "markets": initial,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})

    # 启动后台任务
    tasks = []
    stop_event = asyncio.Event()

    # Polymarket WebSocket 实时订阅
    if "polymarket" in mapping.mappings:
        pm_adapter = registry.get("polymarket")
        if pm_adapter:
            tasks.append(asyncio.create_task(
                _polymarket_ws_stream(websocket, mapping, pm_adapter, stop_event)
            ))

    # Kalshi 轮询（每 5 秒）
    if "kalshi" in mapping.mappings:
        kalshi_adapter = registry.get("kalshi")
        if kalshi_adapter:
            tasks.append(asyncio.create_task(
                _kalshi_poll_stream(websocket, mapping, kalshi_adapter, stop_event)
            ))

    # Betfair 轮询（每 10 秒，节省 API quota）
    if "betfair" in mapping.mappings:
        betfair_adapter = registry.get("betfair")
        if betfair_adapter:
            tasks.append(asyncio.create_task(
                _betfair_poll_stream(websocket, mapping, betfair_adapter, stop_event)
            ))

    # BTX gRPC 实时流
    if "btx" in mapping.mappings:
        btx_adapter = registry.get("btx")
        if btx_adapter:
            # Pre-load runner names for display
            try:
                await btx_adapter._load_runner_names()
            except Exception:
                pass
            tasks.append(asyncio.create_task(
                _btx_grpc_stream(websocket, mapping, btx_adapter, stop_event, btx_market_id)
            ))

    # 监听客户端断开
    try:
        while True:
            try:
                msg = await websocket.receive_text()
                # 客户端可以发 ping
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                break
    finally:
        stop_event.set()
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


async def _fetch_all_orderbooks(mapping, btx_market_id=None) -> dict:
    """获取所有市场的 orderbook（REST 方式）"""
    results = {}
    tasks = []
    market_names = []
    for mname, meid in mapping.mappings.items():
        adapter = registry.get(mname)
        if adapter:
            if mname == "btx" and btx_market_id:
                tasks.append(adapter.fetch_event(btx_market_id))
            elif mname == "betfair" and btx_market_id:
                # Look up Betfair market ID for this specific BTX market
                from database import async_session as _as2, DBBtxMarket
                from sqlalchemy import select as _sel2
                async with _as2() as session:
                    bf_id = (await session.execute(
                        _sel2(DBBtxMarket.betfair_market_id).where(DBBtxMarket.btx_market_id == btx_market_id)
                    )).scalar()
                tasks.append(adapter.fetch_event(bf_id or meid))
            else:
                tasks.append(adapter.fetch_event(meid))
            market_names.append(mname)

    fetched = await asyncio.gather(*tasks, return_exceptions=True)
    for mname, data in zip(market_names, fetched):
        if isinstance(data, Exception):
            results[mname] = [{"error": str(data)}]
        else:
            results[mname] = [ev.model_dump(mode="json") for ev in data]
    return results


async def _polymarket_ws_stream(websocket: WebSocket, mapping, pm_adapter, stop_event):
    """通过 Polymarket WebSocket 订阅实时 orderbook 更新"""
    import websockets
    import json as _json

    pm_event_id = mapping.mappings.get("polymarket", "")
    if not pm_event_id:
        return

    # 获取该事件的所有 token_id
    try:
        resp = await pm_adapter.client.get(
            f"{pm_adapter.GAMMA_URL}/events/{pm_event_id}"
        )
        resp.raise_for_status()
        event_data = resp.json()
    except Exception as e:
        print(f"[ws-pm] Failed to get event data: {e}")
        return

    token_ids = []
    token_meta = {}  # token_id -> {outcome, question}
    for m in event_data.get("markets", []):
        token_ids_raw = m.get("clobTokenIds", "[]")
        tids = _json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
        outcomes_raw = m.get("outcomes", "[]")
        outcomes = _json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        is_neg_risk = event_data.get("negRisk", False)
        question = m.get("groupItemTitle", m.get("question", ""))

        for idx, tid in enumerate(tids):
            if is_neg_risk and idx > 0:
                continue
            token_ids.append(tid)
            token_meta[tid] = {
                "outcome": outcomes[idx] if idx < len(outcomes) else f"Outcome {idx}",
                "title": question,
            }

    if not token_ids:
        return

    PM_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    while not stop_event.is_set():
        try:
            async with websockets.connect(PM_WS_URL, ping_interval=30) as ws:
                # 订阅
                sub_msg = _json.dumps({
                    "assets_ids": token_ids,
                    "type": "market",
                })
                await ws.send(sub_msg)
                print(f"[ws-pm] Subscribed to {len(token_ids)} tokens")

                async for raw_msg in ws:
                    if stop_event.is_set():
                        break
                    try:
                        data = _json.loads(raw_msg)
                        event_type = data.get("event_type", "")

                        if event_type == "book":
                            asset_id = data.get("asset_id", "")
                            meta = token_meta.get(asset_id, {})
                            bids = [{"price": float(b["price"]), "size": float(b["size"])}
                                    for b in data.get("bids", [])]
                            asks = [{"price": float(a["price"]), "size": float(a["size"])}
                                    for a in data.get("asks", [])]
                            await websocket.send_json({
                                "type": "book_update",
                                "market": "polymarket",
                                "asset_id": asset_id,
                                "outcome": meta.get("outcome", ""),
                                "title": meta.get("title", ""),
                                "bids": bids,
                                "asks": asks,
                                "timestamp": data.get("timestamp", ""),
                            })

                        elif event_type == "price_change":
                            changes = data.get("price_changes", [])
                            for pc in changes:
                                asset_id = pc.get("asset_id", "")
                                meta = token_meta.get(asset_id, {})
                                await websocket.send_json({
                                    "type": "price_change",
                                    "market": "polymarket",
                                    "asset_id": asset_id,
                                    "outcome": meta.get("outcome", ""),
                                    "price": pc.get("price"),
                                    "size": pc.get("size"),
                                    "side": pc.get("side"),
                                    "best_bid": pc.get("best_bid"),
                                    "best_ask": pc.get("best_ask"),
                                    "timestamp": data.get("timestamp", ""),
                                })

                        elif event_type == "last_trade_price":
                            asset_id = data.get("asset_id", "")
                            meta = token_meta.get(asset_id, {})
                            await websocket.send_json({
                                "type": "trade",
                                "market": "polymarket",
                                "asset_id": asset_id,
                                "outcome": meta.get("outcome", ""),
                                "price": data.get("price"),
                                "size": data.get("size"),
                                "side": data.get("side"),
                                "timestamp": data.get("timestamp", ""),
                            })

                    except WebSocketDisconnect:
                        return
                    except Exception as e:
                        print(f"[ws-pm] Message error: {e}")

        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[ws-pm] Connection error: {e}, reconnecting in 5s...")
            await asyncio.sleep(5)


async def _kalshi_poll_stream(websocket: WebSocket, mapping, kalshi_adapter, stop_event):
    """Kalshi orderbook 轮询（每 5 秒），因为 WS 需要 API key 认证"""
    kalshi_event_id = mapping.mappings.get("kalshi", "")
    if not kalshi_event_id:
        return

    while not stop_event.is_set():
        try:
            await asyncio.sleep(5)
            if stop_event.is_set():
                break

            events = await kalshi_adapter.fetch_event(kalshi_event_id)
            market_data = [ev.model_dump(mode="json") for ev in events]

            await websocket.send_json({
                "type": "kalshi_update",
                "market": "kalshi",
                "events": market_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[ws-kalshi] Poll error: {e}")
            await asyncio.sleep(5)


async def _betfair_poll_stream(websocket: WebSocket, mapping, betfair_adapter, stop_event):
    """Betfair Stream API 实时推送 orderbook 数据
    使用 SSL TCP 连接 stream-api.betfair.com:443
    如果 Stream API 不可用（缺少认证），回退到 REST 轮询
    """
    import json as _json

    betfair_market_id = mapping.mappings.get("betfair", "")
    if not betfair_market_id:
        return

    # 先尝试获取 runner 名称（用于显示）
    runner_names: dict[int, str] = {}
    try:
        cats = await betfair_adapter.client.post(
            f"{betfair_adapter.REST_URL}/listMarketCatalogue/",
            json={
                "filter": {"marketIds": [betfair_market_id]},
                "marketProjection": ["RUNNER_DESCRIPTION", "EVENT"],
                "maxResults": 1,
            },
            headers=betfair_adapter._rest_headers(),
        )
        if cats.status_code == 200:
            for cat in cats.json():
                for r in cat.get("runners", []):
                    runner_names[r["selectionId"]] = r.get("runnerName", str(r["selectionId"]))
    except Exception:
        pass

    # 尝试 Stream API 连接
    conn = await betfair_adapter.stream_connect()
    if conn:
        reader, writer = conn
        try:
            # 订阅市场
            await betfair_adapter.stream_subscribe_market(writer, [betfair_market_id])

            # 读取实时数据流
            while not stop_event.is_set():
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=30)
                    if not line:
                        break
                    msg = _json.loads(line.decode().strip())
                    op = msg.get("op")

                    if op == "mcm":
                        # MarketChangeMessage
                        for mc in msg.get("mc", []):
                            # 从 marketDefinition 更新 runner 名称
                            mdef = mc.get("marketDefinition")
                            if mdef:
                                for rd in mdef.get("runners", []):
                                    rid = rd.get("id")
                                    if rid:
                                        runner_names.setdefault(rid, str(rid))

                            events = betfair_adapter.parse_market_change(mc, runner_names)
                            if events:
                                market_data = [ev.model_dump(mode="json") for ev in events]
                                await websocket.send_json({
                                    "type": "betfair_update",
                                    "market": "betfair",
                                    "events": market_data,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                })

                    elif op == "status" and msg.get("statusCode") == "FAILURE":
                        print(f"[ws-betfair] Stream error: {msg.get('errorCode')}")
                        break

                except asyncio.TimeoutError:
                    # 发送 heartbeat
                    try:
                        hb = _json.dumps({"op": "heartbeat", "id": 99}) + "\r\n"
                        writer.write(hb.encode())
                        await writer.drain()
                    except Exception:
                        break
                except WebSocketDisconnect:
                    return
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    print(f"[ws-betfair] Stream read error: {e}")
                    break
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

        # Stream 断开后，如果没有停止，回退到轮询
        if not stop_event.is_set():
            print("[ws-betfair] Stream disconnected, falling back to REST polling")

    # 回退: REST 轮询（每 10 秒）
    while not stop_event.is_set():
        try:
            await asyncio.sleep(10)
            if stop_event.is_set():
                break

            events = await betfair_adapter.fetch_event(betfair_market_id)
            market_data = [ev.model_dump(mode="json") for ev in events]

            await websocket.send_json({
                "type": "betfair_update",
                "market": "betfair",
                "events": market_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[ws-betfair] Poll error: {e}")
            await asyncio.sleep(10)


async def _btx_grpc_stream(websocket: WebSocket, mapping, btx_adapter, stop_event, override_market_id=None):
    """BTX gRPC StreamMarketData 实时推送 orderbook 数据"""
    btx_market_id = override_market_id or mapping.mappings.get("btx", "")
    if not btx_market_id:
        return

    while not stop_event.is_set():
        try:
            print(f"[ws-btx] Opening stream for market {btx_market_id}")
            stream = await btx_adapter.stream_market_data(stream_prices=True)
            if stream is None:
                print("[ws-btx] Failed to open stream, retrying in 10s")
                await asyncio.sleep(10)
                continue

            msg_count = 0
            async for msg in stream:
                if stop_event.is_set():
                    break
                msg_count += 1
                if msg.prices and msg.prices.market_prices:
                    parsed = btx_adapter.parse_price_message(msg.prices)
                    if btx_market_id in parsed:
                        events = parsed[btx_market_id]
                        has_data = any(len(e.order_book.bids) > 0 or len(e.order_book.asks) > 0 for e in events)
                        if has_data:
                            market_data = [ev.model_dump(mode="json") for ev in events]
                            await websocket.send_json({
                                "type": "btx_update",
                                "market": "btx",
                                "events": market_data,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })

            print(f"[ws-btx] Stream ended after {msg_count} messages")

        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[ws-btx] Stream error: {e}")
            if not stop_event.is_set():
                await asyncio.sleep(5)


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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
