"""Step 1: 从 Betfair API 获取足球赛事列表，保存到本地 JSON 文件
需要 UK VPN 才能访问 Betfair API
运行: conda run -n pm-liquidity python fetch_betfair_events.py
"""
from __future__ import annotations
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from database import _load_env_file
_load_env_file()
from markets.registry import MarketRegistry


async def main():
    print("=" * 60)
    print("  Step 1: 从 Betfair 获取足球赛事 (需要 UK VPN)")
    print("=" * 60)

    r = MarketRegistry.create_default()
    adapter = r.get("betfair")
    if not adapter:
        print("ERROR: betfair adapter not found")
        return

    print("\n[1] 登录 Betfair...")
    await adapter._ensure_session()
    if not adapter.session_token:
        print("ERROR: 登录失败，请检查 .env 中的 BETFAIR 配置")
        await r.close_all()
        return
    print(f"  ✓ 登录成功")

    print("\n[2] 获取足球赛事...")
    events = await adapter.search_soccer_events("")
    print(f"  ✓ 获取到 {len(events)} 个赛事")

    # 保存到本地
    out_path = os.path.join(os.path.dirname(__file__), "data", "betfair_events.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  ✓ 已保存到 {out_path}")
    print(f"  共 {len(events)} 个赛事")

    # 显示前 10 个
    print("\n  前 10 个赛事:")
    for ev in events[:10]:
        print(f"    {ev['market_id']} | {ev['title']} | {ev.get('end_date', '')}")

    await r.close_all()
    print("\n完成! 接下来请关闭 VPN，运行 Step 2: python match_betfair_events.py")


if __name__ == "__main__":
    asyncio.run(main())
