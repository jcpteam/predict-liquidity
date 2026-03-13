"""事件映射管理 - 以 Polymarket 事件为基础，其他市场映射到 Polymarket 事件上"""
from __future__ import annotations

import json
from pathlib import Path
from models import EventMapping

MAPPING_FILE = Path(__file__).parent / "data" / "event_mappings.json"


class EventMappingStore:
    def __init__(self, filepath: Path = MAPPING_FILE):
        self.filepath = filepath
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._mappings: dict[str, EventMapping] = {}  # key = polymarket event id
        self._load()

    def _load(self):
        if self.filepath.exists():
            raw = json.loads(self.filepath.read_text())
            for uid, data in raw.items():
                self._mappings[uid] = EventMapping(**data)

    def _save(self):
        raw = {uid: m.model_dump(mode="json") for uid, m in self._mappings.items()}
        self.filepath.write_text(json.dumps(raw, indent=2, default=str))

    def sync_from_polymarket(self, events: list[dict]):
        """从 Polymarket 事件列表同步，以 polymarket event id 为 unified_id"""
        existing_ids = set(self._mappings.keys())
        incoming_ids = set()
        for ev in events:
            eid = str(ev.get("id", ""))
            if not eid:
                continue
            incoming_ids.add(eid)
            if eid not in self._mappings:
                self._mappings[eid] = EventMapping(
                    unified_id=eid,
                    display_name=ev.get("title", ""),
                    event_time=ev.get("startDate"),
                    mappings={"polymarket": eid},
                    polymarket_data=ev,
                )
            else:
                # 更新 polymarket 数据
                self._mappings[eid].display_name = ev.get("title", self._mappings[eid].display_name)
                self._mappings[eid].polymarket_data = ev
        self._save()

    def add_market_mapping(self, unified_id: str, market_name: str, market_event_id: str) -> EventMapping | None:
        mapping = self._mappings.get(unified_id)
        if not mapping:
            return None
        mapping.mappings[market_name] = market_event_id
        self._save()
        return mapping

    def remove_market_mapping(self, unified_id: str, market_name: str) -> EventMapping | None:
        mapping = self._mappings.get(unified_id)
        if not mapping:
            return None
        if market_name == "polymarket":
            return mapping  # 不允许移除 polymarket 基础映射
        mapping.mappings.pop(market_name, None)
        self._save()
        return mapping

    def get_mapping(self, unified_id: str) -> EventMapping | None:
        return self._mappings.get(unified_id)

    def list_mappings(self) -> list[EventMapping]:
        return list(self._mappings.values())
