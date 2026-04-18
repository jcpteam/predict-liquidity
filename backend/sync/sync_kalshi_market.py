import asyncio
import os
import sys
from http import client
from logging import critical
from pathlib import Path
import httpx

from db_utils import batch_insert

name = "kalshi"
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

def fetch_all_series() -> list[dict]:
    with httpx.Client(timeout=30) as client:

        params : dict = {
            "tags": "Cricket"
        }
        resp = client.get(
            f"{BASE_URL}/series",
            params=params,
            timeout=30.0,
        )
        resp.raise_for_status()
        all_series = resp.json().get("series", [])
        cricket_series = [
            s for s in all_series
            if "cricket" in [t.lower() for t in (s.get("tags") or [])]
        ]
        return cricket_series

def fetch_events_from_series(series_ticker:str)->list[dict]:
    events = []
    cursor = None

    with httpx.Client(timeout=30) as client:
        while True:
            params: dict = {
                "series_ticker": series_ticker,
                "status": "open",
                "with_nested_markets": "true",
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            for attempt in range(3):
                try:
                    resp = client.get(
                        f"{BASE_URL}/events",
                        params=params,
                        timeout=20.0,
                    )
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        print(f"[kalshi] 429 for {series_ticker}, retry in {wait}s")
                        #asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    batch = data.get("events", [])
                    events.extend(batch)
                    cursor = data.get("cursor")
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"[kalshi] _fetch_events_for_series({series_ticker}) error: {e}")

            else:
                break  # 3次重试都失败
            if not cursor or not batch:
                break
        return events


def fetch_with_limit(ticker: str) -> list[dict]:

    events = []
    cursor = None
    with httpx.Client(timeout=30) as client:
        while True:
            params: dict = {
                "series_ticker": ticker,
                "status": "open",
                "with_nested_markets": "true",
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            for attempt in range(3):
                try:
                    resp = client.get(
                        f"{BASE_URL}/events",
                        params=params,
                        timeout=20.0,
                    )
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        print(f"[kalshi] 429 for {ticker}, retry in {wait}s")

                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    batch = data.get("events", [])
                    events.extend(batch)
                    cursor = data.get("cursor")
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"[kalshi] _fetch_events_for_series({ticker}) error: {e}")
            else:
                break  # 3次重试都失败
            if not cursor or not batch:
                break
    return events

def fetch_events(cricket_series : list[dict]) -> list[dict]:

    #tickers = [s["ticker"] for s in cricket_series if s.get("ticker")]

    all_events: list[dict] = []



    # 分批处理，每批 15 个，批间等待 1.5s
    batch_size = 15
    for se in cricket_series:
        if not se.get("ticker"):
            continue
        #batch = tickers[i:i + batch_size]
        title = se.get("title")
        league = ""
        if "T20" in title:
            league = "T20 Series"
        if "ODI" in title:
            league = "One Day Internationals"
        if "IPL" in title:
            league = "IPL"
        tasks = fetch_with_limit(se.get("ticker")) #[fetch_with_limit(t) for t in batch]
        #batch_results =  asyncio.gather(*tasks, return_exceptions=True)
        for res in tasks:
            if isinstance(res, Exception) or len(res) <= 0:
                continue

            res[0].set("league",league)
            all_events.append(res[0])
#        if i + batch_size < len(tickers):
#            asyncio.sleep(1.5)

    return all_events

def markets_list(cricket_series: list[dict])->list[dict]:

    all_events1: list[dict] = []

    # 分批处理，每批 15 个，批间等待 1.5s
    batch_size = 15
    for se in cricket_series:
        if not se.get("ticker"):
            continue
        #batch = tickers[i:i + batch_size]
        title = se.get("title")
        league = se.get("title")
        if "T20" in title:
            league = "T20 Series"
        if "ODI" in title:
            league = "One Day Internationals"
        if "IPL" in title or "Indian Premier League" in title:
            league = "Indian Premier League"
        tasks = fetch_with_limit(se.get("ticker")) #[fetch_with_limit(t) for t in batch]
        #batch_results =  asyncio.gather(*tasks, return_exceptions=True)
        for res in tasks:
            if isinstance(res, Exception) or len(res) <= 0:
                continue
            res["league"] = league
            all_events1.append(res)

    results = []
    seen_tickers = set()
    for ev in all_events1:
        event_ticker = ev.get("event_ticker", "")
        if event_ticker in seen_tickers:
            continue
        seen_tickers.add(event_ticker)
        title = ev.get("title", "")
        if title and len(title.split("vs") ) >1 :
            title = title.split("vs")[0] + 'v' + title.split("vs")[1]


        # 提取时间：优先用 nested markets 的 close_time
        created_time = ""
        markets = ev.get("markets", [])
        if markets:
            created_time = markets[0].get("expected_expiration_time", "").replace("T", " ").replace("Z", "")
        if not created_time:
            created_time = ev.get("last_updated_ts", "")

        # 收集该 event 下所有 market tickers（用于后续 order book）
        market_tickers = [m.get("ticker", "") for m in markets if m.get("ticker")]

        results.append({
            "market_id": event_ticker,
            "event_id":event_ticker,
            "league":ev.get("league"),
            "display_names": title,
            "item_title":ev.get("sub_title", ""),
            "sport_id":"crkt",
            "status": 0,
            "start_time": created_time,
            #"end_time": close_time,
           # "market_tickers": market_tickers,
            #"category": ev.get("category", ""),
           # "series_ticker": ev.get("series_ticker", ""),
        })

   # print(f"[kalshi] Found {len(results)} soccer events across {len(soccer_series)} series")
    return results

def insert_to_db(market_data: list[dict]):
    """将 Polymarket 市场数据插入到 market_polymarket 表"""
    # 使用通用工具类插入
    batch_insert('market_kalshi', market_data, unique_key='market_id')

def main():
    """获取 Kalshi 所有的板球 series 数据并入库"""
    all_series = fetch_all_series()
    print(f"[Kalshi] Fetched {len(all_series)} events")



    all_markets = markets_list(all_series)
    print(f"[Kalshi] Fetched {len(all_markets)} events")


    """插入数据库"""
    if all_markets:
        insert_to_db(all_markets)


if __name__ == "__main__":
    main()
