"""同步版初始化脚本 - 使用 pymysql 直连，避免 aiomysql 超时问题"""
from __future__ import annotations

import json
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import pymysql
from database import _load_env_file, DB_HOST, DB_PORT, DB_USER, DB_PASSWD, DB_NAME

# Tag processing (same as mapping.py)
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

def get_league_tag(tags):
    for t in tags:
        if t in GENERIC_TAGS:
            continue
        if t and t[0].islower() and ' League' not in t and ' Cup' not in t:
            continue
        return TAG_NORMALIZE.get(t, t)
    return 'Other'

def extract_tags(pm_data):
    tags = []
    for t in pm_data.get("tags", []):
        label = t.get("label", t.get("slug", "")) if isinstance(t, dict) else str(t)
        if label:
            tags.append(label)
    return tags

def parse_datetime(val):
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
        return None


def main():
    print("=" * 60)
    print("  数据库初始化 (同步版 pymysql)")
    print("=" * 60)

    t0 = time.time()
    print(f"\n连接数据库 {DB_HOST}...")
    conn = pymysql.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWD,
        database=DB_NAME, charset='utf8mb4',
        connect_timeout=60, read_timeout=600, write_timeout=600,
    )
    cur = conn.cursor()
    print(f"  ✓ 连接成功 ({time.time()-t0:.1f}s)")

    # 1. 建表
    print("\n[1/4] 创建表...")
    cur.execute("DROP TABLE IF EXISTS market_mappings")
    cur.execute("DROP TABLE IF EXISTS events")
    cur.execute("DROP TABLE IF EXISTS leagues")
    conn.commit()
    print("  旧表已删除")

    cur.execute("""
        CREATE TABLE events (
            unified_id VARCHAR(100) PRIMARY KEY,
            display_name VARCHAR(500) NOT NULL,
            sport VARCHAR(50) DEFAULT 'soccer',
            league VARCHAR(200) DEFAULT 'Other',
            event_time DATETIME NULL,
            end_date DATETIME NULL,
            is_active BOOLEAN DEFAULT TRUE,
            image VARCHAR(1000) NULL,
            liquidity VARCHAR(50) NULL,
            volume VARCHAR(50) NULL,
            volume_24hr VARCHAR(50) NULL,
            market_count INT DEFAULT 0,
            tags_json TEXT NULL,
            polymarket_data_json LONGTEXT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_league (league),
            INDEX idx_active (is_active)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
        CREATE TABLE market_mappings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            unified_id VARCHAR(100) NOT NULL,
            market_name VARCHAR(100) NOT NULL,
            market_event_id VARCHAR(500) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_unified (unified_id),
            UNIQUE KEY uq_mapping_event_market (unified_id, market_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
        CREATE TABLE leagues (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(200) UNIQUE NOT NULL,
            display_name VARCHAR(200) NOT NULL,
            event_count INT DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()
    print("  ✓ 表创建完成")

    # 2. 拉取 Polymarket 足球赛事
    print("\n[2/4] 从 Polymarket 拉取足球赛事...")
    import asyncio
    from markets.registry import MarketRegistry

    async def fetch_pm():
        r = MarketRegistry.create_default()
        adapter = r.get("polymarket")
        evts = await adapter.fetch_all_soccer_events()
        await r.close_all()
        return evts

    events = asyncio.run(fetch_pm())
    print(f"  获取到 {len(events)} 个赛事")

    # 3. 批量写入数据库
    print("\n[3/4] 批量写入数据库...")
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    new_count = 0

    # 第一步：插入基础字段（不含 polymarket_data_json，减少数据量）
    event_sql = """
        INSERT INTO events (unified_id, display_name, sport, league, event_time, end_date,
            is_active, image, liquidity, volume, volume_24hr, market_count,
            tags_json, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            display_name=VALUES(display_name), league=VALUES(league),
            end_date=VALUES(end_date), image=VALUES(image),
            liquidity=VALUES(liquidity), volume=VALUES(volume),
            volume_24hr=VALUES(volume_24hr), market_count=VALUES(market_count),
            tags_json=VALUES(tags_json), is_active=TRUE, updated_at=VALUES(updated_at)
    """

    mapping_sql = """
        INSERT IGNORE INTO market_mappings (unified_id, market_name, market_event_id, created_at)
        VALUES (%s, %s, %s, %s)
    """

    # 存储 JSON 数据用于第二步
    json_updates = []  # [(eid, pm_json), ...]

    batch_size = 200
    for i in range(0, len(events), batch_size):
        batch = events[i:i+batch_size]
        event_rows = []
        mapping_rows = []

        for ev in batch:
            eid = str(ev.get("id", ""))
            if not eid:
                continue
            tags = extract_tags(ev)
            league = get_league_tag(tags)
            end_date_raw = ev.get("endDate", "")
            end_date = parse_datetime(end_date_raw)
            end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else None
            event_time = parse_datetime(ev.get("startDate"))
            event_time_str = event_time.strftime('%Y-%m-%d %H:%M:%S') if event_time else None
            pm_json = json.dumps(ev, default=str)

            event_rows.append((
                eid, ev.get("title", "")[:500], "soccer", league,
                event_time_str, end_date_str, True,
                (ev.get("icon") or ev.get("image") or "")[:1000],
                str(ev.get("liquidity", "")), str(ev.get("volume", "")),
                str(ev.get("volume24hr", "")), len(ev.get("markets", [])),
                json.dumps(tags), now, now,
            ))
            mapping_rows.append((eid, "polymarket", eid, now))
            json_updates.append((pm_json, eid))
            new_count += 1

        t1 = time.time()
        cur.executemany(event_sql, event_rows)
        cur.executemany(mapping_sql, mapping_rows)
        conn.commit()
        elapsed = time.time() - t1
        print(f"  batch {i//batch_size+1}: {len(event_rows)} events ({elapsed:.1f}s)")

    print(f"  ✓ 写入 {new_count} 个赛事")

    # 清理已结束事件
    cur.execute("""
        UPDATE events SET is_active = FALSE
        WHERE end_date < NOW() AND is_active = TRUE
    """)
    expired = cur.rowcount
    conn.commit()
    print(f"  ✓ 标记 {expired} 个已结束事件")

    # 更新联赛表
    cur.execute("DELETE FROM leagues")
    cur.execute("""
        INSERT INTO leagues (name, display_name, event_count, updated_at)
        SELECT league, league, COUNT(*), NOW()
        FROM events WHERE is_active = TRUE
        GROUP BY league
    """)
    conn.commit()
    print("  ✓ 联赛表已更新")

    # 4. 汇总 (Kalshi 自动匹配可通过页面按钮触发)
    cur.execute("SELECT COUNT(*) FROM events WHERE is_active = TRUE")
    active = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leagues")
    league_count = cur.fetchone()[0]

    print("\n" + "=" * 60)
    print(f"  初始化完成! (总耗时 {time.time()-t0:.1f}s)")
    print(f"  活跃赛事: {active}")
    print(f"  联赛分组: {league_count}")
    print(f"  Kalshi 自动匹配请通过页面 '🤖 Auto-Match Markets' 按钮触发")
    print("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
