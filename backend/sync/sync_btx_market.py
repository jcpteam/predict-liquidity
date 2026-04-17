import os
import sys
import json
import httpx
import grpc

sys.path.insert(0, os.path.dirname(__file__))

from database import _load_env_file
from db_utils import batch_insert

_load_env_file()
from datetime import datetime, timezone

from proto.btx.api.v1.customer.betting import betting_api_pb2, betting_api_pb2_grpc
from google.protobuf.json_format import MessageToDict



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

    print("[btx] Streaming ref_data...")
    ref_data = None
    try:
        # Step 1: Get fixtures/competitions/competitors from MATCH_ODDS only (small payload)
        req1 = betting_api_pb2.StreamMarketDataRequest(
            market_types_to_stream=["CRICKET_MATCH_ODDS",
                                    "CRICKET_COMPLETED_MATCH",
                                    "CRICKET_TIED_MATCH",
                                    "CRICKET_INNINGS_SESSION_TOTAL_LINE",
                                    "CRICKET_INNINGS_TOTAL_LINE",
                                    ],
            stream_ref_data=True,
            stream_prices=False,
            stream_ref_data_after_timestamp=0,
        )
        events_data = []
        market_data = []
        stream1 = stub.StreamMarketData(req1, metadata=metadata, timeout=60)
        for msg in stream1:
            rd = MessageToDict(msg.ref_data, preserving_proto_field_name=True)
            comp_map = {
                c["id"]: c.get("display_names", [])[0].get("name", "Other")
                for c in rd.get("competitions", [])
            }

            for events in rd.get("fixtures", []):
                display_names = events.get("display_names", [])
                start_ts = events.get("start_time")
                start_time = datetime.fromtimestamp(int(start_ts) / 1000, tz=timezone.utc) if start_ts else None
                comp_id = events.get("competition_id", "")
                league = comp_map.get(comp_id, "Other")

                events_data.append({
                    "events_id": events.get("id", ""),
                    "display_names": display_names[0].get("name", "") if display_names else "",
                    "start_time": start_time,
                    "league": league,
                    "sport_id": events.get("sport_id", ""),
                })

            events_name_map = {e['events_id']: e['display_names'] for e in events_data}
            league_name_map = {e['events_id']: e['league'] for e in events_data}
            for market in rd.get("markets", []):
                start_ts = market.get("start_time")
                start_time = datetime.fromtimestamp(int(start_ts) / 1000, tz=timezone.utc) if start_ts else None
                display_names = market.get("display_names", [])
                fixture_id = market.get("fixture_id", "")
                runners= market.get("runners", [])
                market_data.append({
                    "market_id": market.get("id", ""),
                    "event_id": fixture_id,
                    "display_names": events_name_map.get(fixture_id, ""),
                    "league": league_name_map.get(fixture_id, ""),
                    "sport_id": market.get("sport_id", ""),
                    "market_type": market.get("market_type", ""),
                    "status": market.get("status", 0),
                    "start_time": start_time,
                    "runners": market.get("runners", ""),
                    "outcomes": market.get("runners", ""),
                    "item_title": "",
                    "neg_risk": False if len(runners) == 2 else True,
                    "type": display_names[0].get("name", "") if display_names else "",
                })

            if len(events_data) > 1 and len(market_data) > 1:
                break
        stream1.cancel()
        
        # 插入数据库
        insert_to_db(market_data)

    except grpc.RpcError as e:
        if ref_data:
            print(f"[btx] Stream ended ({e.code().name}), but got data")
        else:
            print(f"[btx] gRPC error: {e.code().name}: {e.details()}")
    finally:
        channel.close()

    return {"events": events_data, "markets": market_data}


def insert_to_db(market_data):
    """将 BTX 市场数据插入到 market_btx 表"""
    # 处理时间格式和 JSON 序列化
    for m in market_data:
        if m.get('start_time'):
            m['start_time'] = m['start_time'].strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(m.get('runners'), list):
            m['runners'] = json.dumps(m['runners'])
        if isinstance(m.get('outcomes'), list):
            m['outcomes'] = json.dumps(m['outcomes'])
    
    # 使用通用工具类插入
    batch_insert('market_btx', market_data, unique_key='market_id')


def main():
    fetch_btx_ref_data()


if __name__ == "__main__":
    main()
