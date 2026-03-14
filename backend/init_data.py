"""初始化数据库: 建表 → 拉取 Polymarket 足球赛事 → 自动匹配 Kalshi → 存入 MySQL"""
from __future__ import annotations

import asyncio
import sys
import os

# 确保能 import 同目录模块
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, close_db
from mapping import EventMappingStore
from markets.registry import MarketRegistry
from automatch import AutoMatcher


async def main():
    print("=" * 60)
    print("  数据库初始化 & 数据导入")
    print("=" * 60)

    # 1. 建表 (先 drop 再 create，确保 schema 最新)
    print("\n[1/4] 初始化数据库表...")
    from database import engine, Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("  ✓ 表创建完成 (leagues, events, market_mappings)")

    # 2. 拉取 Polymarket 足球赛事
    print("\n[2/4] 从 Polymarket 拉取足球赛事...")
    registry = MarketRegistry.create_default()
    store = EventMappingStore()

    pm_adapter = registry.get("polymarket")
    events = await pm_adapter.fetch_all_soccer_events()
    print(f"  获取到 {len(events)} 个 Polymarket 足球赛事")

    result = await store.sync_from_polymarket(events)
    print(f"  ✓ 新增 {result['new']} 个, 更新 {result['updated']} 个")

    # 3. 清理已结束事件
    print("\n[3/4] 清理已结束事件...")
    expired = await store.cleanup_expired()
    print(f"  ✓ 标记 {expired} 个已结束事件为 inactive")

    # 4. 自动匹配 Kalshi
    print("\n[4/4] 自动匹配 Kalshi 赛事...")
    matcher = AutoMatcher(store, registry)
    kalshi_result = await matcher.auto_match_market("kalshi")
    matched = kalshi_result.get("matched", 0)
    total = kalshi_result.get("total_other_events", 0)
    skipped = kalshi_result.get("skipped", 0)
    print(f"  Kalshi 赛事总数: {total}")
    print(f"  ✓ 匹配成功: {matched}, 跳过: {skipped}")

    if kalshi_result.get("matches"):
        print("\n  匹配详情 (前10条):")
        for m in kalshi_result["matches"][:10]:
            print(f"    [{m['score']:.2f}] {m['polymarket']}")
            print(f"         ↔ {m['other']}")

    # 汇总
    all_mappings = await store.list_mappings()
    leagues = await store.list_leagues()
    print("\n" + "=" * 60)
    print(f"  初始化完成!")
    print(f"  活跃赛事: {len(all_mappings)}")
    print(f"  联赛分组: {len(leagues)}")
    has_kalshi = sum(1 for m in all_mappings if 'kalshi' in m.mappings)
    print(f"  已匹配 Kalshi: {has_kalshi}")
    print("=" * 60)

    await registry.close_all()
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
