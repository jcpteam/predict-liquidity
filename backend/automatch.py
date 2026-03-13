"""自动化事件映射 - 通过队名和比赛时间匹配不同市场的同一足球事件"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional


# ── 队名标准化 ──

# 只移除明确的俱乐部缩写前后缀，不移除有意义的词如 united/city/athletic
TEAM_SUFFIXES = re.compile(
    r'\b(fc|cf|sc|ac|as|ss|rc|cd|ud|sd|ca|se|cr|bv|sv|vfb|tsv|'
    r'afc|sfc|fbpa|fk|nk|sk|pk|'
    r'club|de|da|do|dos|la|le|les|el|al|'
    r'football|futbol|calcio|fussball)\b',
    re.IGNORECASE,
)

# 常见队名别名映射
TEAM_ALIASES: dict[str, str] = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "wolves": "wolverhampton",
    "wolverhampton wanderers": "wolverhampton",
    "west ham united": "west ham",
    "newcastle united": "newcastle",
    "nottm forest": "nottingham forest",
    "nott forest": "nottingham forest",
    "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton",
    "leicester city": "leicester",
    "crystal palace": "crystal palace",
    "sheffield united": "sheffield utd",
    "atletico madrid": "atletico",
    "atletico de madrid": "atletico",
    "club atletico de madrid": "atletico",
    "real madrid cf": "real madrid",
    "fc barcelona": "barcelona",
    "barca": "barcelona",
    "bayern munchen": "bayern munich",
    "bayern münchen": "bayern munich",
    "fc bayern": "bayern munich",
    "borussia dortmund": "dortmund",
    "bv borussia 09 dortmund": "dortmund",
    "rb leipzig": "leipzig",
    "rasenballsport leipzig": "leipzig",
    "bayer leverkusen": "leverkusen",
    "bayer 04 leverkusen": "leverkusen",
    "paris saint germain": "psg",
    "paris saint-germain": "psg",
    "paris sg": "psg",
    "olympique marseille": "marseille",
    "olympique de marseille": "marseille",
    "olympique lyonnais": "lyon",
    "olympique lyon": "lyon",
    "inter milan": "inter",
    "internazionale": "inter",
    "fc internazionale": "inter",
    "ac milan": "milan",
    "juventus fc": "juventus",
    "ssc napoli": "napoli",
    "as roma": "roma",
    "ss lazio": "lazio",
    "athletic club": "athletic bilbao",
    "athletic bilbao": "athletic bilbao",
    "manchester united": "manchester united",
    "manchester city": "manchester city",
    "leicester city": "leicester",
    "stoke city": "stoke",
    "norwich city": "norwich",
    "hull city": "hull",
    "swansea city": "swansea",
}


def normalize_team_name(name: str) -> str:
    """标准化队名：去除重音、后缀、多余空格，转小写"""
    # Unicode 标准化 (去重音)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()

    # 检查别名
    if name in TEAM_ALIASES:
        return TEAM_ALIASES[name]

    # 移除常见后缀
    name = TEAM_SUFFIXES.sub("", name)
    name = re.sub(r'\s+', ' ', name).strip()

    # 再次检查别名（去后缀后）
    if name in TEAM_ALIASES:
        return TEAM_ALIASES[name]

    # 移除数字（如 "09"）
    name = re.sub(r'\b\d{1,4}\b', '', name).strip()
    name = re.sub(r'\s+', ' ', name).strip()

    return name


def extract_teams_from_title(title: str) -> list[str]:
    """从事件标题中提取队名，支持 'Team A vs. Team B' 格式"""
    # 常见分隔符: vs, vs., v, -, @
    parts = re.split(r'\s+(?:vs\.?|v\.?|@|-)\s+', title, maxsplit=1)
    if len(parts) == 2:
        return [normalize_team_name(p.strip()) for p in parts]

    # 尝试从 "Will X win..." 格式提取
    m = re.match(r'will\s+(.+?)\s+win', title, re.IGNORECASE)
    if m:
        return [normalize_team_name(m.group(1))]

    return [normalize_team_name(title)]


def extract_date_from_title(title: str) -> Optional[datetime]:
    """从标题中提取日期，如 '2026-03-14'"""
    m = re.search(r'(\d{4}-\d{2}-\d{2})', title)
    if m:
        try:
            return datetime.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


# ── 匹配评分 ──

def team_similarity(name_a: str, name_b: str) -> float:
    """计算两个标准化队名的相似度 (0~1)"""
    if name_a == name_b:
        return 1.0

    # 一个包含另一个
    if name_a in name_b or name_b in name_a:
        return 0.85

    # 基于词集合的 Jaccard 相似度
    words_a = set(name_a.split())
    words_b = set(name_b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    jaccard = len(intersection) / len(union)

    return jaccard


def time_proximity_score(t1: Optional[datetime], t2: Optional[datetime], max_hours: float = 48) -> float:
    """计算两个时间的接近程度 (0~1)，在 max_hours 内线性衰减"""
    if t1 is None or t2 is None:
        return 0.5  # 无时间信息时给中性分
    # 确保都是 naive 或都是 aware
    if t1.tzinfo is not None and t2.tzinfo is None:
        t2 = t2.replace(tzinfo=t1.tzinfo)
    elif t2.tzinfo is not None and t1.tzinfo is None:
        t1 = t1.replace(tzinfo=t2.tzinfo)
    diff_hours = abs((t1 - t2).total_seconds()) / 3600
    if diff_hours > max_hours:
        return 0.0
    return 1.0 - (diff_hours / max_hours)


def compute_match_score(
    pm_teams: list[str],
    pm_time: Optional[datetime],
    other_teams: list[str],
    other_time: Optional[datetime],
) -> float:
    """
    计算 Polymarket 事件与其他市场事件的匹配分数 (0~1)
    权重: 队名匹配 70%, 时间接近 30%
    """
    # 队名匹配：找最佳配对
    if not pm_teams or not other_teams:
        return 0.0

    team_scores = []
    for pt in pm_teams:
        best = max(team_similarity(pt, ot) for ot in other_teams)
        team_scores.append(best)

    # 双向匹配
    for ot in other_teams:
        best = max(team_similarity(ot, pt) for pt in pm_teams)
        team_scores.append(best)

    avg_team_score = sum(team_scores) / len(team_scores) if team_scores else 0.0

    # 时间匹配
    time_score = time_proximity_score(pm_time, other_time)

    # 加权
    final = 0.7 * avg_team_score + 0.3 * time_score
    return final


# ── 自动映射引擎 ──

class AutoMatcher:
    """自动将其他市场的足球事件映射到 Polymarket 事件"""

    MATCH_THRESHOLD = 0.6  # 最低匹配分数

    def __init__(self, mapping_store, registry):
        self.mapping_store = mapping_store
        self.registry = registry

    def _parse_polymarket_event(self, mapping) -> tuple[list[str], Optional[datetime]]:
        """从 Polymarket 映射中提取队名和时间"""
        title = mapping.display_name or ""
        teams = extract_teams_from_title(title)
        event_time = None
        if mapping.event_time:
            event_time = mapping.event_time
        elif mapping.polymarket_data:
            end_str = mapping.polymarket_data.get("endDate", "")
            if end_str:
                try:
                    event_time = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
        # 也尝试从标题提取日期
        title_date = extract_date_from_title(title)
        if title_date and not event_time:
            event_time = title_date
        return teams, event_time

    def _parse_other_event(self, event_data: dict) -> tuple[list[str], Optional[datetime]]:
        """从其他市场事件数据中提取队名和时间"""
        title = event_data.get("title", "")
        teams = extract_teams_from_title(title)
        event_time = None
        for time_field in ["end_date", "close_time", "marketStartTime", "start_time"]:
            ts = event_data.get(time_field, "")
            if ts:
                try:
                    event_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    break
                except (ValueError, TypeError):
                    continue
        if not event_time:
            event_time = extract_date_from_title(title)
        return teams, event_time

    async def auto_match_market(self, market_name: str) -> dict:
        """
        对指定市场执行自动映射：
        1. 获取该市场所有足球事件
        2. 与 Polymarket 事件逐一比较
        3. 超过阈值的自动建立映射
        返回 {matched: int, skipped: int, errors: int}
        """
        adapter = self.registry.get(market_name)
        if not adapter:
            return {"error": f"Market '{market_name}' not found"}

        # 获取其他市场的事件列表
        try:
            other_events = await adapter.search_soccer_events("")
        except Exception as e:
            return {"error": str(e), "matched": 0}

        pm_mappings = self.mapping_store.list_mappings()
        matched = 0
        skipped = 0
        results = []

        for other_ev in other_events:
            other_teams, other_time = self._parse_other_event(other_ev)
            if not other_teams or not other_teams[0]:
                skipped += 1
                continue

            best_score = 0.0
            best_pm_id = None
            best_pm_name = ""

            for pm in pm_mappings:
                # 跳过已经有该市场映射的
                if market_name in pm.mappings:
                    continue
                pm_teams, pm_time = self._parse_polymarket_event(pm)
                if not pm_teams or not pm_teams[0]:
                    continue
                score = compute_match_score(pm_teams, pm_time, other_teams, other_time)
                if score > best_score:
                    best_score = score
                    best_pm_id = pm.unified_id
                    best_pm_name = pm.display_name

            if best_score >= self.MATCH_THRESHOLD and best_pm_id:
                other_id = other_ev.get("market_id", "")
                self.mapping_store.add_market_mapping(best_pm_id, market_name, other_id)
                matched += 1
                results.append({
                    "polymarket": best_pm_name,
                    "other": other_ev.get("title", ""),
                    "score": round(best_score, 3),
                    "market_id": other_id,
                })
            else:
                skipped += 1

        return {
            "market": market_name,
            "matched": matched,
            "skipped": skipped,
            "total_other_events": len(other_events),
            "matches": results,
        }

    async def auto_match_all(self) -> list[dict]:
        """对所有非 polymarket 市场执行自动映射"""
        results = []
        for market_name in self.registry.list_markets():
            if market_name == "polymarket":
                continue
            result = await self.auto_match_market(market_name)
            results.append(result)
        return results
