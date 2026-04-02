"""以 BTX 为主的同步脚本

流程:
1. 通过 gRPC StreamMarketData 获取 BTX 足球 ref_data（fixtures + markets）
2. 以 BTX fixture 为主键写入 events 表 + btx/betfair mapping
3. 在线拉取 Polymarket 足球事件，自动匹配到 BTX
4. 在线拉取 Kalshi 足球事件，自动匹配到 BTX（如果可用）

用法: conda run -n pm-liquidity python3 backend/sync_btx_primary.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'proto'))

from database import _load_env_file, DB_HOST, DB_PORT, DB_USER, DB_PASSWD, DB_NAME
_load_env_file()

import pymysql
import httpx
import grpc
from btx.api.v1.customer.betting import betting_api_pb2, betting_api_pb2_grpc
from google.protobuf.json_format import MessageToDict
from automatch import (
    normalize_team_name, extract_teams_from_title,
    compute_match_score,
)

MATCH_THRESHOLD = 0.55


def parse_dt(val):
    if not val:
        return None
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val / 1000, tz=timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    # Try as millisecond timestamp
    try:
        ts = int(s)
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    except (ValueError, OSError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def get_en_name(display_names):
    """从 display_names 列表中提取英文名"""
    for dn in display_names:
        if dn.get("language_code") == "en" and "*" in dn.get("region_codes", []):
            return dn.get("name", "")
    for dn in display_names:
        if dn.get("language_code") == "en":
            return dn.get("name", "")
    if display_names:
        return display_names[0].get("name", "")
    return ""


def get_mapping_value(mappings, source, key):
    """从 mappings 列表中提取指定 source+key 的 value"""
    for m in mappings:
        if m.get("source") == source and m.get("key") == key:
            return m.get("value", "")
    return ""


# ── Step 1: Fetch BTX ref_data via gRPC ──

def fetch_btx_ref_data():
    """通过 gRPC StreamMarketData 获取 BTX 足球 ref_data"""
    client_id = os.getenv("BTX_CLIENT_ID")
    client_secret = os.getenv("BTX_CLIENT_SECRET")
    account_id = os.getenv("BTX_ACCOUNT_ID")

    print(f"[btx] Authenticating (account={account_id})...")
    resp = httpx.post(
        "https://auth.prod.ex3.io/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code != 200:
        print(f"[btx] Auth failed: {resp.text}")
        return None
    token = resp.json()["access_token"]
    print("[btx] Token OK")

    channel = grpc.secure_channel("api.prod.ex3.io:443", grpc.ssl_channel_credentials(),
        options=[("grpc.max_receive_message_length", 50 * 1024 * 1024)])
    stub = betting_api_pb2_grpc.BettingApiStub(channel)
    metadata = [("authorization", f"Bearer {token}"), ("x-account-id", account_id)]

    req = betting_api_pb2.StreamMarketDataRequest(
        market_types_to_stream=[
            "FOOTBALL_FULL_TIME_MATCH_ODDS",
            "FOOTBALL_FULL_TIME_TOTAL_GOALS_OVER_UNDER",
            "FOOTBALL_FULL_TIME_ASIAN_HANDICAP",
            "FOOTBALL_FULL_TIME_ASIAN_HANDICAP_TOTAL_GOALS",
            "FOOTBALL_FULL_TIME_CORRECT_SCORE",
        ],
        stream_ref_data=True,
        stream_ref_data_after_timestamp=0,
    )

    print("[btx] Streaming ref_data...")
    ref_data = None
    try:
        stream = stub.StreamMarketData(req, metadata=metadata, timeout=30)
        for msg in stream:
            if msg.ref_data and msg.ref_data.timestamp > 0:
                ref_data = MessageToDict(msg.ref_data, preserving_proto_field_name=True)
                print(f"[btx] Got ref_data: {len(ref_data.get('fixtures', []))} fixtures, "
                      f"{len(ref_data.get('markets', []))} markets, "
                      f"{len(ref_data.get('competitions', []))} competitions, "
                      f"{len(ref_data.get('competitors', []))} competitors")
                break
    except grpc.RpcError as e:
        if ref_data:
            print(f"[btx] Stream ended ({e.code().name}), but got data")
        else:
            print(f"[btx] gRPC error: {e.code().name}: {e.details()}")
    finally:
        channel.close()

    return ref_data


# ── Step 2: Write BTX data to DB ──

def write_btx_to_db(ref_data):
    """以 BTX fixture 为主键写入 events 表，同时写入 btx + betfair mapping"""
    fixtures = ref_data.get("fixtures", [])
    markets = ref_data.get("markets", [])
    competitions = ref_data.get("competitions", [])
    competitors = ref_data.get("competitors", [])

    # Build lookup maps
    comp_map = {c["id"]: get_en_name(c.get("display_names", [])) for c in competitions}
    competitor_map = {c["id"]: get_en_name(c.get("display_names", [])) for c in competitors}
    market_by_fixture = {}
    for m in markets:
        fid = m.get("fixture_id", "")
        if fid:
            market_by_fixture.setdefault(fid, []).append(m)

    print(f"\n[db] Connecting to {DB_HOST}...")
    conn = pymysql.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWD,
        database=DB_NAME, charset='utf8mb4',
        connect_timeout=60, read_timeout=600, write_timeout=600,
    )
    cur = conn.cursor()
    print("[db] Connected")

    # Clear old data
    cur.execute("DELETE FROM events")
    cur.execute("DELETE FROM market_mappings")
    cur.execute("DELETE FROM leagues")
    conn.commit()
    print("[db] Cleared old data")

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    event_sql = """INSERT INTO events (unified_id, display_name, sport, league, event_time,
        end_date, is_active, image, liquidity, volume, volume_24hr, market_count,
        tags_json, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE display_name=VALUES(display_name), league=VALUES(league),
        event_time=VALUES(event_time), is_active=TRUE, updated_at=VALUES(updated_at)"""

    mapping_sql = """INSERT IGNORE INTO market_mappings
        (unified_id, market_name, market_event_id, created_at)
        VALUES (%s,%s,%s,%s)"""

    event_rows = []
    btx_mappings = []
    betfair_mappings = []

    for fix in fixtures:
        fid = fix.get("id", "")
        if not fid:
            continue
        title = get_en_name(fix.get("display_names", []))
        if not title:
            continue
        comp_id = fix.get("competition_id", "")
        league = comp_map.get(comp_id, "Other")
        start_time = parse_dt(fix.get("start_time"))
        start_str = start_time.strftime('%Y-%m-%d %H:%M:%S') if start_time else None
        is_active = start_time > datetime.now(timezone.utc) if start_time else True

        event_rows.append((
            fid, title[:500], "soccer", league, start_str, start_str,
            is_active, "", "", "", "", 0, "[]", now, now,
        ))

        # BTX mapping: use market_id from markets
        fix_markets = market_by_fixture.get(fid, [])
        if fix_markets:
            btx_market_id = fix_markets[0].get("id", "")
            btx_mappings.append((fid, "btx", btx_market_id, now))

            # Betfair mapping from BTX market mappings
            betfair_market_id = get_mapping_value(fix_markets[0].get("mappings", []), "Betfair", "MarketId")
            if betfair_market_id:
                betfair_mappings.append((fid, "betfair", betfair_market_id, now))

    # Batch insert
    batch = 200
    for i in range(0, len(event_rows), batch):
        cur.executemany(event_sql, event_rows[i:i+batch])
        conn.commit()
    print(f"[db] Inserted {len(event_rows)} events")

    all_mappings = btx_mappings + betfair_mappings
    for i in range(0, len(all_mappings), batch):
        cur.executemany(mapping_sql, all_mappings[i:i+batch])
        conn.commit()
    print(f"[db] Inserted {len(btx_mappings)} BTX + {len(betfair_mappings)} Betfair mappings")

    # Update leagues
    cur.execute("DELETE FROM leagues")
    cur.execute("""INSERT INTO leagues (name, display_name, event_count, updated_at)
        SELECT league, league, COUNT(*), NOW() FROM events GROUP BY league""")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM events")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leagues")
    league_count = cur.fetchone()[0]
    print(f"[db] {total} events, {league_count} leagues")

    conn.close()
    return len(event_rows)


# ── Step 3: Match Polymarket events to BTX ──

def match_polymarket_to_btx():
    """拉取 Polymarket 足球事件，匹配到 BTX fixtures"""
    import asyncio
    from markets.registry import MarketRegistry

    async def fetch_pm():
        r = MarketRegistry.create_default()
        pm = r.get("polymarket")
        events = await pm.fetch_all_soccer_events()
        await r.close_all()
        return events

    print("\n[polymarket] Fetching events...")
    pm_events = asyncio.run(fetch_pm())
    print(f"[polymarket] Got {len(pm_events)} events")

    # Load BTX events from DB for matching
    conn = pymysql.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWD,
        database=DB_NAME, charset='utf8mb4',
    )
    cur = conn.cursor()
    cur.execute("SELECT unified_id, display_name, event_time FROM events")
    btx_events = cur.fetchall()

    # Check existing polymarket mappings
    cur.execute("SELECT unified_id FROM market_mappings WHERE market_name='polymarket'")
    existing_pm = {r[0] for r in cur.fetchall()}

    btx_parsed = []
    for uid, title, evt in btx_events:
        if uid in existing_pm:
            continue
        teams = extract_teams_from_title(title)
        btx_parsed.append((uid, title, teams, evt))

    matched = 0
    used_btx = set()
    mapping_rows = []

    for pm_ev in pm_events:
        pm_id = str(pm_ev.get("id", ""))
        pm_title = pm_ev.get("title", "")
        if not pm_id or not pm_title:
            continue
        # Skip non-match events
        if not re.search(r'\s+(?:vs\.?|v\.?|@)\s+', pm_title, re.IGNORECASE):
            continue

        pm_teams = extract_teams_from_title(pm_title)
        pm_time = None
        for tf in ["endDate", "startDate"]:
            ts = pm_ev.get(tf, "")
            if ts:
                try:
                    pm_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    break
                except:
                    pass

        best_score = 0.0
        best_uid = None
        for uid, btitle, bteams, btime in btx_parsed:
            if uid in used_btx:
                continue
            if not bteams or not bteams[0]:
                continue
            score = compute_match_score(bteams, btime, pm_teams, pm_time)
            if score > best_score:
                best_score = score
                best_uid = uid

        if best_score >= MATCH_THRESHOLD and best_uid:
            used_btx.add(best_uid)
            mapping_rows.append((best_uid, "polymarket", pm_id, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')))
            matched += 1

    if mapping_rows:
        mapping_sql = "INSERT IGNORE INTO market_mappings (unified_id, market_name, market_event_id, created_at) VALUES (%s,%s,%s,%s)"
        cur.executemany(mapping_sql, mapping_rows)
        conn.commit()

    print(f"[polymarket] Matched {matched} events to BTX")
    conn.close()
    return matched


# ── Step 4: Match Kalshi (if available) ──

def match_kalshi_to_btx():
    """拉取 Kalshi 足球事件，匹配到 BTX"""
    import asyncio
    from markets.registry import MarketRegistry

    async def fetch_kalshi():
        r = MarketRegistry.create_default()
        k = r.get("kalshi")
        events = await k.search_soccer_events("")
        await r.close_all()
        return events

    print("\n[kalshi] Fetching events...")
    try:
        kalshi_events = asyncio.run(fetch_kalshi())
        print(f"[kalshi] Got {len(kalshi_events)} events")
    except Exception as e:
        print(f"[kalshi] Failed: {e}")
        return 0

    conn = pymysql.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWD,
        database=DB_NAME, charset='utf8mb4',
    )
    cur = conn.cursor()
    cur.execute("SELECT unified_id, display_name, event_time FROM events")
    btx_events = cur.fetchall()
    cur.execute("SELECT unified_id FROM market_mappings WHERE market_name='kalshi'")
    existing = {r[0] for r in cur.fetchall()}

    btx_parsed = [(uid, t, extract_teams_from_title(t), et) for uid, t, et in btx_events if uid not in existing]

    matched = 0
    used = set()
    rows = []
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    for kev in kalshi_events:
        ktitle = kev.get("title", "")
        kid = kev.get("market_id", "")
        if not ktitle or not kid:
            continue
        kteams = extract_teams_from_title(ktitle)
        ktime = parse_dt(kev.get("end_date") or kev.get("close_time"))

        best_score = 0.0
        best_uid = None
        for uid, _, bteams, btime in btx_parsed:
            if uid in used or not bteams or not bteams[0]:
                continue
            score = compute_match_score(bteams, btime, kteams, ktime)
            if score > best_score:
                best_score = score
                best_uid = uid

        if best_score >= MATCH_THRESHOLD and best_uid:
            used.add(best_uid)
            rows.append((best_uid, "kalshi", kid, now))
            matched += 1

    if rows:
        cur.executemany("INSERT IGNORE INTO market_mappings (unified_id, market_name, market_event_id, created_at) VALUES (%s,%s,%s,%s)", rows)
        conn.commit()

    print(f"[kalshi] Matched {matched} events to BTX")
    conn.close()
    return matched


# ── Main ──

def main():
    t0 = time.time()
    print("=" * 60)
    print("  BTX-Primary Sync")
    print("=" * 60)

    # Step 1: Fetch BTX ref_data
    ref_data = fetch_btx_ref_data()
    if not ref_data:
        print("Failed to fetch BTX data")
        return

    # Save raw data
    with open("backend/data/btx_ref_data.json", "w") as f:
        json.dump(ref_data, f, indent=2, default=str)
    print(f"[btx] Saved to backend/data/btx_ref_data.json")

    # Step 2: Write to DB
    count = write_btx_to_db(ref_data)

    # Step 3: Match Polymarket
    try:
        match_polymarket_to_btx()
    except Exception as e:
        print(f"[polymarket] Error: {e}")

    # Step 4: Match Kalshi
    try:
        match_kalshi_to_btx()
    except Exception as e:
        print(f"[kalshi] Error: {e}")

    # Summary
    conn = pymysql.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWD,
        database=DB_NAME, charset='utf8mb4',
    )
    cur = conn.cursor()
    cur.execute("SELECT market_name, COUNT(*) FROM market_mappings GROUP BY market_name")
    mappings = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM events")
    total = cur.fetchone()[0]
    conn.close()

    print(f"\n{'=' * 60}")
    print(f"  Done in {time.time()-t0:.1f}s")
    print(f"  Events: {total}")
    for mname, cnt in mappings:
        print(f"  {mname} mappings: {cnt}")
    print("=" * 60)


if __name__ == "__main__":
    main()
