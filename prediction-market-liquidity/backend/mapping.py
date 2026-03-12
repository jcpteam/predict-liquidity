"""事件映射管理 - 将不同市场的同一足球事件关联起来"""

import json
import uuid
from pathlib import Path
from models import EventMapping

MAPPING_FILE = Path(__file__).parent / "data" / "event_mappings.json"


class EventMappingStore:
    def __init__(self, filepath: Path = MAPPING_FILE):
        self.filepath = filepath
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._mappings: dict[str, EventMapping] = {}
        self._load()

    def _load(self):
        if self.filepath.exists():
            raw = json.loads(self.filepath.read_text())
            for uid, data in raw.items():
                self._mappings[uid] = EventMapping(**data)

    def _save(self):
        raw = {uid: m.model_dump(mode="json") for uid, m in self._mappings.items()}
        self.filepath.write_text(json.dumps(raw, indent=2, default=str))

    def create_mapping(self, display_name: str, event_time: str | None = None) -> EventMapping:
        uid = str(uuid.uuid4())[:8]
        mapping = EventMapping(
            unified_id=uid,
            display_name=display_name,
            event_time=event_time,
            mappings={},
        )
        self._mappings[uid] = mapping
        self._save()
        return mapping

    def add_market_to_mapping(self, unified_id: str, market_name: str, market_event_id: str) -> EventMapping | None:
        mapping = self._mappings.get(unified_id)
        if not mapping:
            return None
        mapping.mappings[market_name] = market_event_id
        self._save()
        return mapping

    def remove_market_from_mapping(self, unified_id: str, market_name: str) -> EventMapping | None:
        mapping = self._mappings.get(unified_id)
        if not mapping:
            return None
        mapping.mappings.pop(market_name, None)
        self._save()
        return mapping

    def delete_mapping(self, unified_id: str) -> bool:
        if unified_id in self._mappings:
            del self._mappings[unified_id]
            self._save()
            return True
        return False

    def get_mapping(self, unified_id: str) -> EventMapping | None:
        return self._mappings.get(unified_id)

    def list_mappings(self) -> list[EventMapping]:
        return list(self._mappings.values())

    def find_by_market_event(self, market_name: str, market_event_id: str) -> EventMapping | None:
        for m in self._mappings.values():
            if m.mappings.get(market_name) == market_event_id:
                return m
        return None
