import os
import sys
import json
import httpx

sys.path.insert(0, os.path.dirname(__file__))

from database import _load_env_file
from db_utils import batch_insert

_load_env_file()

BASE_URL = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"


def fetch_all_cricket_events() -> list[dict]:
    """获取 Polymarket 上所有活跃的板球赛事（以 tag_id=517 为主）"""
    all_events = []
    offset = 0
    limit = 100

    with httpx.Client(timeout=30) as client:
        while True:
            try:
                resp = client.get(
                    f"{GAMMA_URL}/events",
                    params={
                        "tag_id": 517,
                        "active": "true",
                        "closed": "false",
                        "limit": limit,
                        "offset": offset,
                        "order": "liquidity",
                        "ascending": "false",
                    },
                )
                resp.raise_for_status()
                events = resp.json()
                if not events:
                    break
                all_events.extend(events)
                if len(events) < limit:
                    break
                offset += limit
            except Exception as e:
                print(f"[polymarket] fetch_all_soccer_events error at offset {offset}: {type(e).__name__}: {e}")
                import traceback;
                traceback.print_exc()
                break

    return all_events


def market_list(events: list[dict]) -> list[dict]:
    """解析 events 数据，提取 market 信息"""
    market_datas = []
    for event in events:
        markets = event.get("markets", [])
        if event.get("id") == '256575':
            print(event)
        for market in markets:
            title = event.get("title", "")
            question = market.get("question", "")
            league = title.split(":")[0]
            if "T20 Series" in league:
                league = "T20 Series"
            if "ODI" in league:
                league = "One Day Internationals"
            if len(title.split(" - ")) < 2:
                display_names = title.split(":")[1] if len(title.split(":")) > 1 else title.split(":")[0]
                if len(question.split(" - ")) >= 2:
                    mtype = question.split(" - ")[1]
                else:
                    mtype = "Match Odds" if " vs " in title else "Other"
            else:
                display_names = title.split(" - ")[0].split(":")[1]
                mtype = title.split(" - ")[1]
            if "Women" in title:
                display_names = display_names.split(" vs")[0] + " W vs " + display_names.split(" vs")[1] + " W"

            market_datas.append({
                "market_id": market.get("id", ""),
                "event_id": event.get("id", ""),
                "display_names": display_names.strip().replace(" vs ", " v ").replace("Royal Challengers Bangalore", "Royal Challengers Bengaluru"),
                "league": league,
                "sport_id": "crkt",
                "market_type": '',
                "status": 0,
                "start_time": event.get("startTime", "").replace("T", " ").replace("Z", ""),
                "runners": market.get("clobTokenIds", []),
                "outcomes": market.get("outcomes", []),
                "item_title": market.get("groupItemTitle", ""),
                "neg_risk": market.get("negRisk", False),
                "type": mtype.replace("?", ""),
            })
    return market_datas


def insert_to_db(market_data: list[dict]):
    """将 Polymarket 市场数据插入到 market_polymarket 表"""
    # 使用通用工具类插入
    batch_insert('market_polymarket', market_data, unique_key='market_id')


def main():
    """获取 Polymarket 所有的板球 events 数据并入库"""
    all_events = fetch_all_cricket_events()
    print(f"[polymarket] Fetched {len(all_events)} events")

    """解析出 market 数据"""
    market_data = market_list(all_events)
    print(f"[polymarket] Parsed {len(market_data)} markets")

    """插入数据库"""
    if market_data:
        insert_to_db(market_data)


if __name__ == "__main__":
    main()
