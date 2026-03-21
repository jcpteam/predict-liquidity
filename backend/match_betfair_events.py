"""Step 2: 将本地 Betfair 赛事 JSON 匹配到数据库中的 Polymarket 事件
不需要 VPN，直接连接 AWS RDS
运行: conda run -n pm-liquidity python match_betfair_events.py
"""
from __future__ import annotations
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import pymysql
from database import _load_env_file, DB_HOST, DB_PORT, DB_USER, DB_PASSWD, DB_NAME
from automatch import (
    extract_teams_from_title, extract_date_from_title,
    compute_match_score, normalize_team_name,
)
from datetime import datetime


MATCH_THRESHOLD = 0.55  # 稍微降低阈值，增加匹配率


def main():
    # 读取本地 Betfair 赛事
    data_path = os.path.join(os.path.dirname(__file__), "data", "betfair_events.json")
    if not os.path.exists(data_path):
        print(f"ERROR: {data_path} 不存在")
        print("请先运行 Step 1: python fetch_betfair_events.py (需要 UK VPN)")
        return

    with open(data_path, "r", encoding="utf-8") as f:
        betfair_events = json.load(f)
    print(f"读取到 {len(betfair_events)} 个 Betfair 赛事")

    # 连接数据库
    print(f"\n连接数据库 {DB_HOST}...")
    t0 = time.time()
    conn = pymysql.connect(
        host=DB_HOST, port=int(DB_PORT), user=DB_USER, password=DB_PASSWD,
        database=DB_NAME, charset='utf8mb4',
        connect_timeout=60, read_timeout=120, write_timeout=120,
    )
    cur = conn.cursor()
    print(f"  ✓ 连接成功 ({time.time()-t0:.1f}s)")

    # 获取所有活跃的 Polymarket 事件
    cur.execute("""
        SELECT e.unified_id, e.display_name, e.event_time, e.end_date
        FROM events e
        WHERE e.is_active = TRUE
    """)
    pm_events = cur.fetchall()
    print(f"  数据库中有 {len(pm_events)} 个活跃 Polymarket 事件")

    # 获取已有的 betfair 映射
    cur.execute("SELECT unified_id, market_event_id FROM market_mappings WHERE market_name = 'betfair'")
    existing = {row[1]: row[0] for row in cur.fetchall()}
    print(f"  已有 {len(existing)} 个 Betfair 映射")

    # 解析 Polymarket 事件
    pm_parsed = []
    for uid, name, etime, edate in pm_events:
        teams = extract_teams_from_title(name or "")
        pm_parsed.append({
            "unified_id": uid,
            "display_name": name,
            "teams": teams,
            "event_time": etime,
            "end_date": edate,
        })

    # 匹配
    matched = 0
    skipped = 0
    results = []

    for bf_ev in betfair_events:
        bf_id = bf_ev.get("market_id", "")
        bf_title = bf_ev.get("title", "")

        # 跳过已映射的
        if bf_id in existing:
            skipped += 1
            continue

        bf_teams = extract_teams_from_title(bf_title)
        bf_time = None
        ts = bf_ev.get("end_date", "")
        if ts:
            try:
                bf_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        if not bf_teams or not bf_teams[0]:
            skipped += 1
            continue

        best_score = 0.0
        best_pm = None

        for pm in pm_parsed:
            if not pm["teams"] or not pm["teams"][0]:
                continue
            score = compute_match_score(pm["teams"], pm["event_time"], bf_teams, bf_time)
            if score > best_score:
                best_score = score
                best_pm = pm

        if best_score >= MATCH_THRESHOLD and best_pm:
            # 写入映射
            try:
                cur.execute("""
                    INSERT INTO market_mappings (unified_id, market_name, market_event_id, created_at)
                    VALUES (%s, 'betfair', %s, NOW())
                    ON DUPLICATE KEY UPDATE market_event_id = VALUES(market_event_id)
                """, (best_pm["unified_id"], bf_id))
                matched += 1
                results.append({
                    "score": round(best_score, 3),
                    "betfair": bf_title,
                    "betfair_id": bf_id,
                    "polymarket": best_pm["display_name"],
                    "pm_id": best_pm["unified_id"],
                })
            except Exception as e:
                print(f"  写入失败: {e}")
        else:
            skipped += 1

    conn.commit()

    # 汇总
    cur.execute("SELECT COUNT(*) FROM market_mappings WHERE market_name = 'betfair'")
    total_bf = cur.fetchone()[0]

    print(f"\n{'='*60}")
    print(f"  匹配完成!")
    print(f"  新匹配: {matched}")
    print(f"  跳过: {skipped}")
    print(f"  Betfair 总映射数: {total_bf}")
    print(f"{'='*60}")

    if results:
        print(f"\n  匹配详情 (前 30 个):")
        for r in results[:30]:
            print(f"    [{r['score']}] {r['betfair']}")
            print(f"         → {r['polymarket']}")
            print()

    conn.close()


if __name__ == "__main__":
    main()
