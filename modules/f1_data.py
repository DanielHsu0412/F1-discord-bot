"""
modules/f1_data.py — 資料來源模組（Data Module）

透過 OpenF1 API 取得 F1 賽程資料，整合為統一結構。
"""

import logging
import re
import requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from config import OPENF1_BASE_URL, API_TIMEOUT

logger = logging.getLogger(__name__)

# ── Session 名稱對照（英文 → 顯示用） ─────────────────────────
SESSION_DISPLAY_NAMES: dict[str, str] = {
    "Practice 1": "FP1",
    "Practice 2": "FP2",
    "Practice 3": "FP3",
    "Qualifying": "Qualifying",
    "Sprint Qualifying": "Sprint Qualifying",
    "Sprint": "Sprint",
    "Race": "Race",
}

# Session 排序權重（同一天內按此順序顯示）
SESSION_ORDER_WEIGHT: dict[str, int] = {
    "Practice 1": 1,
    "Practice 2": 2,
    "Practice 3": 3,
    "Sprint Qualifying": 4,
    "Sprint": 5,
    "Qualifying": 6,
    "Race": 7,
}

# 需要發送「單場提醒」的 session 類型
REMINDER_SESSIONS: set[str] = {"Qualifying", "Sprint Qualifying", "Sprint", "Race"}


@dataclass
class F1Session:
    """單個 Session 資料結構。"""
    session_key: int
    session_name: str
    date_start: datetime
    date_end: Optional[datetime]
    meeting_key: int
    meeting_name: str
    country_name: str
    circuit_short_name: str
    year: int

    @property
    def display_name(self) -> str:
        return SESSION_DISPLAY_NAMES.get(self.session_name, self.session_name)

    @property
    def order_weight(self) -> int:
        return SESSION_ORDER_WEIGHT.get(self.session_name, 99)

    @property
    def needs_reminder(self) -> bool:
        return self.session_name in REMINDER_SESSIONS

    @property
    def is_race(self) -> bool:
        return self.session_name == "Race"


@dataclass
class F1Meeting:
    """單站大獎賽資料結構，包含所有 sessions。"""
    meeting_key: int
    meeting_name: str
    country_name: str
    circuit_short_name: str
    year: int
    sessions: list[F1Session] = field(default_factory=list)

    @property
    def is_sprint_weekend(self) -> bool:
        return any(
            s.session_name in ("Sprint", "Sprint Qualifying")
            for s in self.sessions
        )

    @property
    def race_session(self) -> Optional[F1Session]:
        for s in self.sessions:
            if s.is_race:
                return s
        return None

    @property
    def sorted_sessions(self) -> list[F1Session]:
        return sorted(self.sessions, key=lambda s: s.date_start)

    def sessions_needing_reminder(self) -> list[F1Session]:
        return [s for s in self.sorted_sessions if s.needs_reminder]


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """解析 OpenF1 的時間字串為 UTC datetime。"""
    if not dt_str:
        return None
    try:
        dt_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError) as e:
        logger.warning(f"無法解析時間字串 '{dt_str}': {e}")
        return None


def _fetch_json(url: str, params: dict | None = None) -> Optional[list]:
    """通用 GET 請求，回傳 JSON 或 None（錯誤時）。"""
    try:
        resp = requests.get(url, params=params, timeout=API_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.error(f"API 請求逾時：{url}")
    except requests.exceptions.ConnectionError:
        logger.error(f"無法連線至 API：{url}")
    except requests.exceptions.HTTPError as e:
        logger.error(f"API HTTP 錯誤 {e.response.status_code}：{url}")
    except Exception as e:
        logger.error(f"API 未知錯誤：{e}")
    return None


def _clean_meeting_name(
    meeting_name: Optional[str],
    meeting_official_name: Optional[str],
    country_name: Optional[str],
    circuit_short_name: Optional[str],
) -> str:
    """
    優先使用 meeting_name。
    如果沒有，就退回 meeting_official_name。
    再不行才退回 country / circuit。
    """
    name = (meeting_name or "").strip()
    official = (meeting_official_name or "").strip()
    country = (country_name or "").strip()
    circuit = (circuit_short_name or "").strip()

    if name:
        return name

    if official:
        # 去掉尾端年份，例如 "... GRAND PRIX 2026"
        official = re.sub(r"\s+\d{4}$", "", official).strip()

        # 如果是全大寫，稍微轉好看一點
        if official.isupper():
            official = official.title()

        return official

    if country:
        return f"{country} GP"

    if circuit:
        return f"{circuit} GP"

    return "Unknown GP"


def fetch_meetings_meta_for_year(year: int) -> dict[int, dict]:
    """
    取得年度 meetings 資料，建立 meeting_key -> metadata 對照表。
    這樣就算 sessions 缺少 meeting_name，也能補回正確站名。
    """
    data = _fetch_json(f"{OPENF1_BASE_URL}/meetings", params={"year": year})
    if data is None:
        return {}

    meetings_meta: dict[int, dict] = {}

    for raw in data:
        meeting_key = raw.get("meeting_key", 0)
        if not meeting_key:
            continue

        country_name = raw.get("country_name", "") or ""
        circuit_short_name = raw.get("circuit_short_name", "") or ""

        meetings_meta[meeting_key] = {
            "meeting_name": _clean_meeting_name(
                raw.get("meeting_name"),
                raw.get("meeting_official_name"),
                country_name,
                circuit_short_name,
            ),
            "country_name": country_name,
            "circuit_short_name": circuit_short_name,
        }

    logger.info(f"取得 {len(meetings_meta)} 筆 meetings metadata（{year} 年）")
    return meetings_meta


def fetch_sessions_for_year(year: int) -> list[F1Session]:
    """
    從 OpenF1 取得指定年度的所有 sessions。
    過濾掉測試賽與無效資料。
    """
    data = _fetch_json(f"{OPENF1_BASE_URL}/sessions", params={"year": year})
    if data is None:
        return []

    meetings_meta = fetch_meetings_meta_for_year(year)
    sessions: list[F1Session] = []

    for raw in data:
        session_name = raw.get("session_name", "")

        if "testing" in session_name.lower() or "pre-season" in session_name.lower():
            continue

        date_start = _parse_datetime(raw.get("date_start"))
        if date_start is None:
            continue

        meeting_key = raw.get("meeting_key", 0)
        meta = meetings_meta.get(meeting_key, {})

        country_name = raw.get("country_name") or meta.get("country_name", "")
        circuit_short_name = raw.get("circuit_short_name") or meta.get("circuit_short_name", "")

        resolved_meeting_name = _clean_meeting_name(
            raw.get("meeting_name"),
            raw.get("meeting_official_name"),
            country_name,
            circuit_short_name,
        )

        # 如果 sessions 這邊還是沒有，就用 meetings endpoint 補
        if resolved_meeting_name == "Unknown GP":
            resolved_meeting_name = meta.get("meeting_name", "Unknown GP")

        sessions.append(F1Session(
            session_key=raw.get("session_key", 0),
            session_name=session_name,
            date_start=date_start,
            date_end=_parse_datetime(raw.get("date_end")),
            meeting_key=meeting_key,
            meeting_name=resolved_meeting_name,
            country_name=country_name,
            circuit_short_name=circuit_short_name,
            year=raw.get("year", year),
        ))

    logger.info(f"取得 {len(sessions)} 個 sessions（{year} 年）")
    return sessions


def group_sessions_into_meetings(sessions: list[F1Session]) -> list[F1Meeting]:
    """
    將 sessions 依 meeting_key 分組，建立 F1Meeting 清單。
    以 Race session 開始時間排序（由早到晚）。
    """
    meetings_map: dict[int, F1Meeting] = {}

    for session in sessions:
        mk = session.meeting_key

        if mk not in meetings_map:
            meetings_map[mk] = F1Meeting(
                meeting_key=mk,
                meeting_name=session.meeting_name,
                country_name=session.country_name,
                circuit_short_name=session.circuit_short_name,
                year=session.year,
            )
        else:
            # 若前面拿到 Unknown GP，後面有更好的名字就補上
            if (
                meetings_map[mk].meeting_name == "Unknown GP"
                and session.meeting_name != "Unknown GP"
            ):
                meetings_map[mk].meeting_name = session.meeting_name

            if not meetings_map[mk].country_name and session.country_name:
                meetings_map[mk].country_name = session.country_name

            if not meetings_map[mk].circuit_short_name and session.circuit_short_name:
                meetings_map[mk].circuit_short_name = session.circuit_short_name

        meetings_map[mk].sessions.append(session)

    meetings = list(meetings_map.values())
    meetings.sort(key=lambda m: (
        m.race_session.date_start if m.race_session else datetime.max.replace(tzinfo=timezone.utc)
    ))

    logger.info(f"整合為 {len(meetings)} 站大獎賽")
    return meetings


def get_current_year_meetings() -> list[F1Meeting]:
    """
    取得當前年度的所有大獎賽（含完整 session 資料）。
    """
    now = datetime.now(tz=timezone.utc)
    year = now.year
    sessions = fetch_sessions_for_year(year)
    if not sessions:
        logger.warning(f"無法取得 {year} 年賽程資料")
        return []
    return group_sessions_into_meetings(sessions)


def get_upcoming_meetings(meetings: list[F1Meeting]) -> list[F1Meeting]:
    """
    過濾出尚未結束的大獎賽（Race session 尚未開始）。
    """
    now = datetime.now(tz=timezone.utc)
    upcoming = []
    for meeting in meetings:
        race = meeting.race_session
        if race and race.date_start > now:
            upcoming.append(meeting)
    return upcoming