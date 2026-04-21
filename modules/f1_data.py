"""
modules/f1_data.py — 資料來源模組（Data Module）

透過 OpenF1 API 取得 F1 賽程資料，整合為統一結構。
另外提供：
- 車手積分榜
- 車隊積分榜
- 本季各站正賽冠軍歷史
"""

import logging
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

import requests

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

COUNTRY_ZH_MAP: dict[str, str] = {
    "Australia": "澳洲",
    "China": "中國",
    "Japan": "日本",
    "Bahrain": "巴林",
    "Saudi Arabia": "沙烏地阿拉伯",
    "United States": "美國",
    "Italy": "義大利",
    "Monaco": "摩納哥",
    "Spain": "西班牙",
    "Canada": "加拿大",
    "Austria": "奧地利",
    "United Kingdom": "英國",
    "Belgium": "比利時",
    "Hungary": "匈牙利",
    "Netherlands": "荷蘭",
    "Azerbaijan": "亞塞拜然",
    "Singapore": "新加坡",
    "Mexico": "墨西哥",
    "Brazil": "巴西",
    "Qatar": "卡達",
    "United Arab Emirates": "阿拉伯聯合大公國",
}

CIRCUIT_ZH_MAP: dict[str, str] = {
    "Albert Park": "墨爾本",
    "Melbourne": "墨爾本",
    "Shanghai": "上海",
    "Suzuka": "鈴鹿",
    "Sakhir": "薩基爾",
    "Jeddah": "吉達",
    "Miami": "邁阿密",
    "Imola": "伊莫拉",
    "Monaco": "摩納哥",
    "Catalunya": "加泰隆尼亞",
    "Barcelona": "巴塞隆納",
    "Montreal": "蒙特婁",
    "Gilles Villeneuve": "蒙特婁",
    "Spielberg": "斯皮爾堡",
    "Red Bull Ring": "紅牛環",
    "Silverstone": "銀石",
    "Spa-Francorchamps": "斯帕",
    "Hungaroring": "匈牙利站",
    "Zandvoort": "贊德沃特",
    "Monza": "蒙札",
    "Baku": "巴庫",
    "Marina Bay": "濱海灣",
    "Singapore": "新加坡",
    "Austin": "奧斯汀",
    "COTA": "奧斯汀",
    "Circuit of the Americas": "奧斯汀",
    "Mexico City": "墨西哥城",
    "Interlagos": "聖保羅",
    "Sao Paulo": "聖保羅",
    "São Paulo": "聖保羅",
    "Las Vegas": "拉斯維加斯",
    "Lusail": "路薩爾",
    "Yas Marina": "亞斯碼頭",
    "Madrid": "馬德里",
    "Madring": "馬德里",
}

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
    name_acronym: str
    team_name: str


@dataclass
class TeamStanding:
    position: int
    points: float
    team_name: str


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


def _fetch_json(url: str, params: dict | None = None) -> Optional[list]:
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


def _normalize_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _translate_country(country_name: Optional[str]) -> str:
    country = _normalize_text(country_name)
    return COUNTRY_ZH_MAP.get(country, country)


def _translate_circuit(circuit_short_name: Optional[str]) -> str:
    circuit = _normalize_text(circuit_short_name)
    return CIRCUIT_ZH_MAP.get(circuit, circuit)


def _build_chinese_meeting_name(
    country_name: Optional[str],
    circuit_short_name: Optional[str],
    meeting_name: Optional[str],
    meeting_official_name: Optional[str],
) -> str:
    country_en = _normalize_text(country_name)
    circuit_en = _normalize_text(circuit_short_name)

    special = SPECIAL_MEETING_NAME_MAP.get((country_en, circuit_en))
    if special:
        return special

    country_zh = _translate_country(country_en)
    circuit_zh = _translate_circuit(circuit_en)

    if country_zh and circuit_zh:
        if country_zh == circuit_zh:
            return f"{country_zh}大獎賽"
        return f"{country_zh}{circuit_zh}大獎賽"

    cleaned_meeting_name = _normalize_text(meeting_name)
    if cleaned_meeting_name:
        return cleaned_meeting_name

    if meeting_official_name:
        return meeting_official_name

    if country_zh:
        return f"{country_zh}大獎賽"

    return "未知大獎賽"


def fetch_meetings_meta_for_year(year: int) -> dict[int, dict]:
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

        meeting_name_zh = _build_chinese_meeting_name(
            country_name=country_name,
            circuit_short_name=circuit_short_name,
            meeting_name=raw.get("meeting_name"),
            meeting_official_name=raw.get("meeting_official_name"),
        )

        meetings_meta[meeting_key] = {
            "meeting_name": meeting_name_zh,
            "country_name": country_name,
            "circuit_short_name": circuit_short_name,
        }

    logger.info(f"取得 {len(meetings_meta)} 筆 meetings metadata（{year} 年）")
    return meetings_meta


def fetch_sessions_for_year(year: int) -> list[F1Session]:
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

        resolved_meeting_name = _build_chinese_meeting_name(
            country_name=country_name,
            circuit_short_name=circuit_short_name,
            meeting_name=raw.get("meeting_name"),
            meeting_official_name=raw.get("meeting_official_name"),
        )

        sessions.append(F1Session(
            session_key=raw.get("session_key", 0),
            session_name=session_name,
            date_start=date_start,
            date_end=_parse_datetime(raw.get("date_end")),
            meeting_key=meeting_key,
            meeting_name=resolved_meeting_name or meta.get("meeting_name", "未知大獎賽"),
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
    now = datetime.now(tz=timezone.utc)
    year = now.year
    sessions = fetch_sessions_for_year(year)
    if not sessions:
        logger.warning(f"無法取得 {year} 年賽程資料")
        return []
    return group_sessions_into_meetings(sessions)


def get_upcoming_meetings(meetings: list[F1Meeting]) -> list[F1Meeting]:
    now = datetime.now(tz=timezone.utc)
    return [
        meeting for meeting in meetings
        if meeting.race_session and meeting.race_session.date_start > now
    ]


def _get_latest_completed_race_session(year: Optional[int] = None) -> Optional[F1Session]:
    if year is None:
        year = datetime.now(tz=timezone.utc).year

    sessions = fetch_sessions_for_year(year)
    if not sessions:
        return None

    now = datetime.now(tz=timezone.utc)
    race_sessions = [
        s for s in sessions
        if s.session_name == "Race" and s.date_start <= now
    ]

    if not race_sessions:
        return None

    race_sessions.sort(key=lambda s: s.date_start, reverse=True)
    return race_sessions[0]


def fetch_driver_standings(year: Optional[int] = None) -> list[DriverStanding]:
    latest_race = _get_latest_completed_race_session(year)
    if latest_race is None:
        logger.warning("目前找不到可用的正賽 session，無法取得車手積分榜")
        return []

    standings_raw = _fetch_json(
        f"{OPENF1_BASE_URL}/championship_drivers",
        params={"session_key": latest_race.session_key}
    )
    if not standings_raw:
        return []

    drivers_raw = _fetch_json(
        f"{OPENF1_BASE_URL}/drivers",
        params={"session_key": latest_race.session_key}
    ) or []

    driver_map = {d.get("driver_number", 0): d for d in drivers_raw}

    standings: list[DriverStanding] = []
    for row in standings_raw:
        driver_number = row.get("driver_number", 0)
        info = driver_map.get(driver_number, {})

        standings.append(DriverStanding(
            position=int(row.get("position_current", 999)),
            points=float(row.get("points_current", 0)),
            driver_number=driver_number,
            full_name=info.get("full_name", f"#{driver_number}"),
            name_acronym=info.get("name_acronym", ""),
            team_name=info.get("team_name", ""),
        ))

    standings.sort(key=lambda x: x.position)
    return standings


def fetch_team_standings(year: Optional[int] = None) -> list[TeamStanding]:
    latest_race = _get_latest_completed_race_session(year)
    if latest_race is None:
        logger.warning("目前找不到可用的正賽 session，無法取得車隊積分榜")
        return []

    standings_raw = _fetch_json(
        f"{OPENF1_BASE_URL}/championship_teams",
        params={"session_key": latest_race.session_key}
    )
    if not standings_raw:
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


def fetch_race_results_history(year: Optional[int] = None) -> list[dict]:
    """
    取得本季每站正賽冠軍歷史。
    回傳格式：
    [
      {"grand_prix": "...", "winner": "...", "team": "..."},
      ...
    ]
    """
    if year is None:
        year = datetime.now(tz=timezone.utc).year

    meetings = get_current_year_meetings()
    now = datetime.now(tz=timezone.utc)

    finished_races = []
    for meeting in meetings:
        race = meeting.race_session
        if race and race.date_start <= now:
            finished_races.append((meeting, race))

    results = []

    for meeting, race in finished_races:
        session_result_raw = _fetch_json(
            f"{OPENF1_BASE_URL}/session_result",
            params={"session_key": race.session_key}
        )

        if not session_result_raw:
            continue

        winner_row = None
        for row in session_result_raw:
            position = row.get("position")
            if position == 1:
                winner_row = row
                break

        if not winner_row:
            continue

        full_name = winner_row.get("full_name", "Unknown Driver")
        team_name = winner_row.get("team_name", "Unknown Team")

        results.append({
            "grand_prix": meeting.meeting_name,
            "winner": full_name,
            "team": team_name,
        })

    return results