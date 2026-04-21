"""
modules/f1_data.py — Data module for F1 Taiwan Bot

功能：
- 取得當年度賽程
- 取得下一站資訊
- 取得最新 Drivers' Standings
- 取得最新 Constructors' Standings
- 取得本季各站 Race winners
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
    "Practice 1": "FP1",
    "Practice 2": "FP2",
    "Practice 3": "FP3",
    "Qualifying": "Qualifying",
    "Sprint Qualifying": "Sprint Qualifying",
    "Sprint": "Sprint",
    "Race": "Race",
}

SESSION_ORDER_WEIGHT: dict[str, int] = {
    "Practice 1": 1,
    "Practice 2": 2,
    "Practice 3": 3,
    "Sprint Qualifying": 4,
    "Sprint": 5,
    "Qualifying": 6,
    "Race": 7,
}

REMINDER_SESSIONS: set[str] = {"Qualifying", "Sprint Qualifying", "Sprint", "Race"}

# ── 中文 GP 名稱對照（你前面要的格式）────────────────────────
SPECIAL_MEETING_NAME_MAP: dict[tuple[str, str], str] = {
    ("United States", "Miami"): "美國邁阿密大獎賽",
    ("United States", "Austin"): "美國奧斯汀大獎賽",
    ("United States", "Circuit of the Americas"): "美國奧斯汀大獎賽",
    ("United States", "COTA"): "美國奧斯汀大獎賽",
    ("United States", "Las Vegas"): "美國拉斯維加斯大獎賽",
    ("United Kingdom", "Silverstone"): "英國銀石大獎賽",
    ("Italy", "Monza"): "義大利蒙札大獎賽",
    ("Saudi Arabia", "Jeddah"): "沙烏地阿拉伯吉達大獎賽",
    ("United Arab Emirates", "Yas Marina"): "阿布達比亞斯碼頭大獎賽",
    ("Spain", "Barcelona"): "西班牙巴塞隆納大獎賽",
    ("Spain", "Catalunya"): "西班牙加泰隆尼亞大獎賽",
    ("Canada", "Montreal"): "加拿大蒙特婁大獎賽",
    ("Belgium", "Spa-Francorchamps"): "比利時斯帕大獎賽",
    ("Brazil", "Interlagos"): "巴西聖保羅大獎賽",
    ("Brazil", "São Paulo"): "巴西聖保羅大獎賽",
    ("Brazil", "Sao Paulo"): "巴西聖保羅大獎賽",
    ("Qatar", "Lusail"): "卡達路薩爾大獎賽",
    ("Monaco", "Monaco"): "摩納哥大獎賽",
    ("Japan", "Suzuka"): "日本鈴鹿大獎賽",
    ("Australia", "Melbourne"): "澳洲墨爾本大獎賽",
    ("Australia", "Albert Park"): "澳洲墨爾本大獎賽",
    ("China", "Shanghai"): "中國上海大獎賽",
    ("Bahrain", "Sakhir"): "巴林薩基爾大獎賽",
    ("Austria", "Red Bull Ring"): "奧地利紅牛環大獎賽",
    ("Azerbaijan", "Baku"): "亞塞拜然巴庫大獎賽",
    ("Singapore", "Marina Bay"): "新加坡濱海灣大獎賽",
    ("Mexico", "Mexico City"): "墨西哥城大獎賽",
}


@dataclass
class F1Session:
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


@dataclass
class DriverStanding:
    position: int
    points: float
    driver_number: int
    full_name: str
    team_name: str


@dataclass
class TeamStanding:
    position: int
    points: float
    team_name: str


@dataclass
class RaceResult:
    grand_prix: str
    date_label: str
    winner: str
    team: str


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
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


def _fetch_json(url: str, params: dict | None = None):
    try:
        resp = requests.get(url, params=params, timeout=API_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.error(f"API timeout: {url}")
    except requests.exceptions.ConnectionError:
        logger.error(f"API connection error: {url}")
    except requests.exceptions.HTTPError as e:
        logger.error(f"API HTTP error {e.response.status_code}: {url}")
    except Exception as e:
        logger.error(f"API unknown error: {e}")
    return None


def _resolve_meeting_name(country_name: str, circuit_short_name: str, fallback: str) -> str:
    key = (country_name or "", circuit_short_name or "")
    if key in SPECIAL_MEETING_NAME_MAP:
        return SPECIAL_MEETING_NAME_MAP[key]
    if fallback:
        return fallback
    if country_name:
        return f"{country_name} GP"
    return "Unknown GP"


def fetch_sessions_for_year(year: int) -> list[F1Session]:
    data = _fetch_json(f"{OPENF1_BASE_URL}/sessions", params={"year": year})
    if data is None:
        return []

    sessions = []
    for raw in data:
        session_name = raw.get("session_name", "")
        if "testing" in session_name.lower() or "pre-season" in session_name.lower():
            continue

        date_start = _parse_datetime(raw.get("date_start"))
        if date_start is None:
            continue

        country_name = raw.get("country_name", "") or ""
        circuit_short_name = raw.get("circuit_short_name", "") or ""
        fallback_name = raw.get("meeting_name", "") or ""

        sessions.append(F1Session(
            session_key=raw.get("session_key", 0),
            session_name=session_name,
            date_start=date_start,
            date_end=_parse_datetime(raw.get("date_end")),
            meeting_key=raw.get("meeting_key", 0),
            meeting_name=_resolve_meeting_name(country_name, circuit_short_name, fallback_name),
            country_name=country_name,
            circuit_short_name=circuit_short_name,
            year=raw.get("year", year),
        ))

    logger.info(f"取得 {len(sessions)} 個 sessions（{year} 年）")
    return sessions


def group_sessions_into_meetings(sessions: list[F1Session]) -> list[F1Meeting]:
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

    meetings = list(meetings_map.values())
    meetings.sort(key=lambda m: (
        m.race_session.date_start if m.race_session else datetime.max.replace(tzinfo=timezone.utc)
    ))

    logger.info(f"整合為 {len(meetings)} 站大獎賽")
    return meetings


def get_current_year_meetings() -> list[F1Meeting]:
    year = datetime.now(tz=timezone.utc).year
    sessions = fetch_sessions_for_year(year)
    if not sessions:
        logger.warning(f"無法取得 {year} 年賽程資料")
        return []
    return group_sessions_into_meetings(sessions)


def get_upcoming_meetings(meetings: list[F1Meeting]) -> list[F1Meeting]:
    now = datetime.now(tz=timezone.utc)
    return [m for m in meetings if m.race_session and m.race_session.date_start > now]


def _get_latest_completed_race_session(year: Optional[int] = None) -> Optional[F1Session]:
    if year is None:
        year = datetime.now(tz=timezone.utc).year

    sessions = fetch_sessions_for_year(year)
    if not sessions:
        return None

    now = datetime.now(tz=timezone.utc)
    race_sessions = [s for s in sessions if s.session_name == "Race" and s.date_start <= now]
    if not race_sessions:
        return None

    race_sessions.sort(key=lambda s: s.date_start, reverse=True)
    return race_sessions[0]


def fetch_driver_standings(year: Optional[int] = None) -> list[DriverStanding]:
    latest_race = _get_latest_completed_race_session(year)
    if latest_race is None:
        logger.warning("沒有已完成的正賽，無法取得 drivers standings")
        return []

    session_key = latest_race.session_key

    standings_raw = _fetch_json(
        f"{OPENF1_BASE_URL}/championship_drivers",
        params={"session_key": session_key}
    )
    if not standings_raw:
        logger.warning("championship_drivers 回傳空資料")
        return []

    drivers_raw = _fetch_json(
        f"{OPENF1_BASE_URL}/drivers",
        params={"session_key": session_key}
    ) or []

    driver_map: dict[int, dict] = {
        int(d.get("driver_number", 0)): d for d in drivers_raw
    }

    standings: list[DriverStanding] = []
    for row in standings_raw:
        driver_number = int(row.get("driver_number", 0))
        info = driver_map.get(driver_number, {})

        full_name = (
            info.get("full_name")
            or f"Driver #{driver_number}"
        )

        team_name = info.get("team_name") or "Unknown Team"

        standings.append(DriverStanding(
            position=int(row.get("position_current", 999)),
            points=float(row.get("points_current", 0)),
            driver_number=driver_number,
            full_name=full_name,
            team_name=team_name,
        ))

    standings.sort(key=lambda x: x.position)
    return standings


def fetch_team_standings(year: Optional[int] = None) -> list[TeamStanding]:
    latest_race = _get_latest_completed_race_session(year)
    if latest_race is None:
        logger.warning("沒有已完成的正賽，無法取得 constructors standings")
        return []

    session_key = latest_race.session_key

    standings_raw = _fetch_json(
        f"{OPENF1_BASE_URL}/championship_teams",
        params={"session_key": session_key}
    )
    if not standings_raw:
        logger.warning("championship_teams 回傳空資料")
        return []

    standings: list[TeamStanding] = []
    for row in standings_raw:
        standings.append(TeamStanding(
            position=int(row.get("position_current", 999)),
            points=float(row.get("points_current", 0)),
            team_name=row.get("team_name", "Unknown Team"),
        ))

    standings.sort(key=lambda x: x.position)
    return standings


def fetch_race_results_history(year: Optional[int] = None) -> list[RaceResult]:
    if year is None:
        year = datetime.now(tz=timezone.utc).year

    meetings = get_current_year_meetings()
    now = datetime.now(tz=timezone.utc)

    results: list[RaceResult] = []

    for meeting in meetings:
        race = meeting.race_session
        if race is None or race.date_start > now:
            continue

        session_key = race.session_key

        session_result_raw = _fetch_json(
            f"{OPENF1_BASE_URL}/session_result",
            params={"session_key": session_key}
        )
        if not session_result_raw:
            continue

        winner_row = None
        for row in session_result_raw:
            if int(row.get("position", 999)) == 1:
                winner_row = row
                break

        if winner_row is None:
            continue

        driver_number = int(winner_row.get("driver_number", 0))

        drivers_raw = _fetch_json(
            f"{OPENF1_BASE_URL}/drivers",
            params={"session_key": session_key}
        ) or []

        driver_info = None
        for d in drivers_raw:
            if int(d.get("driver_number", 0)) == driver_number:
                driver_info = d
                break

        winner_name = "Unknown Driver"
        team_name = "Unknown Team"

        if driver_info:
            winner_name = driver_info.get("full_name") or winner_name
            team_name = driver_info.get("team_name") or team_name

        date_label = race.date_start.strftime("%d %b")

        results.append(RaceResult(
            grand_prix=meeting.meeting_name,
            date_label=date_label,
            winner=winner_name,
            team=team_name,
        ))

    return results