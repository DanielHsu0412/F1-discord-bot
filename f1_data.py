"""
modules/f1_data.py — 資料來源模組（Data Module）

透過 OpenF1 API 取得 F1 賽程資料，整合為統一結構。
API 文件：https://openf1.org/
"""

import logging
import requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from config import OPENF1_BASE_URL, API_TIMEOUT

logger = logging.getLogger(__name__)

# ── Session 名稱對照（英文 → 顯示用） ─────────────────────────
SESSION_DISPLAY_NAMES: dict[str, str] = {
    "Practice 1":        "FP1",
    "Practice 2":        "FP2",
    "Practice 3":        "FP3",
    "Qualifying":        "Qualifying",
    "Sprint Qualifying": "Sprint Qualifying",
    "Sprint":            "Sprint",
    "Race":              "Race",
}

# Session 排序權重（同一天內按此順序顯示）
SESSION_ORDER_WEIGHT: dict[str, int] = {
    "Practice 1":        1,
    "Practice 2":        2,
    "Practice 3":        3,
    "Sprint Qualifying": 4,
    "Sprint":            5,
    "Qualifying":        6,
    "Race":              7,
}

# 需要發送「單場提醒」的 session 類型
REMINDER_SESSIONS: set[str] = {"Qualifying", "Sprint Qualifying", "Sprint", "Race"}


@dataclass
class F1Session:
    """單個 Session 資料結構。"""
    session_key: int
    session_name: str           # 原始英文名稱
    date_start: datetime        # UTC 時間
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
        """是否為 Sprint 週末。"""
        return any(
            s.session_name in ("Sprint", "Sprint Qualifying")
            for s in self.sessions
        )

    @property
    def race_session(self) -> Optional[F1Session]:
        """取得正賽 session（用於計算賽前通知時間）。"""
        for s in self.sessions:
            if s.is_race:
                return s
        return None

    @property
    def sorted_sessions(self) -> list[F1Session]:
        """按時間排序的 sessions。"""
        return sorted(self.sessions, key=lambda s: s.date_start)

    def sessions_needing_reminder(self) -> list[F1Session]:
        """回傳需要提醒的 sessions。"""
        return [s for s in self.sorted_sessions if s.needs_reminder]


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """解析 OpenF1 的時間字串為 UTC datetime。"""
    if not dt_str:
        return None
    try:
        # 格式可能是 "2025-05-02T18:30:00+00:00" 或 "2025-05-02T18:30:00Z"
        dt_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
        # 確保有時區資訊
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError) as e:
        logger.warning(f"無法解析時間字串 '{dt_str}': {e}")
        return None


def _fetch_json(url: str, params: dict = None) -> Optional[list]:
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


def fetch_sessions_for_year(year: int) -> list[F1Session]:
    """
    從 OpenF1 取得指定年度的所有 sessions。
    過濾掉測試賽與無效資料。
    """
    data = _fetch_json(f"{OPENF1_BASE_URL}/sessions", params={"year": year})
    if data is None:
        return []

    sessions = []
    for raw in data:
        session_name = raw.get("session_name", "")

        # 過濾掉測試賽
        if "testing" in session_name.lower() or "pre-season" in session_name.lower():
            continue

        date_start = _parse_datetime(raw.get("date_start"))
        if date_start is None:
            continue  # 無開始時間的 session 跳過

        sessions.append(F1Session(
            session_key=raw.get("session_key", 0),
            session_name=session_name,
            date_start=date_start,
            date_end=_parse_datetime(raw.get("date_end")),
            meeting_key=raw.get("meeting_key", 0),
            meeting_name=raw.get("meeting_name", "Unknown GP"),
            country_name=raw.get("country_name", ""),
            circuit_short_name=raw.get("circuit_short_name", ""),
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
        meetings_map[mk].sessions.append(session)

    # 依 Race session 時間排序
    meetings = list(meetings_map.values())
    meetings.sort(key=lambda m: (
        m.race_session.date_start if m.race_session else datetime.max.replace(tzinfo=timezone.utc)
    ))

    logger.info(f"整合為 {len(meetings)} 站大獎賽")
    return meetings


def get_current_year_meetings() -> list[F1Meeting]:
    """
    取得當前年度的所有大獎賽（含完整 session 資料）。
    這是對外的主要介面。
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
    過濾出「尚未結束」的大獎賽（Race session 尚未開始）。
    """
    now = datetime.now(tz=timezone.utc)
    upcoming = []
    for meeting in meetings:
        race = meeting.race_session
        if race and race.date_start > now:
            upcoming.append(meeting)
    return upcoming
