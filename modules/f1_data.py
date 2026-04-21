"""
modules/f1_data.py — 資料來源模組（Data Module）

透過 OpenF1 API 取得 F1 賽程資料，整合為統一結構。
站名會優先轉成中文版，例如：
- 美國邁阿密大獎賽
- 英國銀石大獎賽
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

# ── 國家中文對照 ──────────────────────────────────────────────
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
    "France": "法國",
    "Germany": "德國",
    "Portugal": "葡萄牙",
    "Turkey": "土耳其",
    "Russia": "俄羅斯",
    "South Africa": "南非",
    "Argentina": "阿根廷",
    "Thailand": "泰國",
}

# ── 賽道 / 地點中文對照（優先決定站名特色）────────────────────
CIRCUIT_ZH_MAP: dict[str, str] = {
    "Albert Park": "墨爾本",
    "Melbourne": "墨爾本",
    "Shanghai": "上海",
    "Suzuka": "鈴鹿",
    "Sakhir": "薩基爾",
    "Jeddah": "吉達",
    "Miami": "邁阿密",
    "Imola": "伊莫拉",
    "Monaco": "蒙地卡羅",
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
    "Mugello": "穆傑羅",
    "Portimao": "波爾蒂芒",
    "Istanbul Park": "伊斯坦堡",
    "Sepang": "雪邦",
    "Hockenheim": "霍根海姆",
    "Nürburgring": "紐柏林",
    "Nurburgring": "紐柏林",
    "Paul Ricard": "保羅里卡德",
    "Kyalami": "凱拉米",
}

# 某些站名如果用 country + circuit 會顯得怪，直接用這裡覆蓋
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

# 從 official name 裡面抓可能的地名關鍵字
OFFICIAL_NAME_KEYWORD_MAP: dict[str, str] = {
    "MIAMI": "邁阿密",
    "BRITISH": "英國",
    "SILVERSTONE": "銀石",
    "JAPANESE": "日本",
    "SUZUKA": "鈴鹿",
    "BAHRAIN": "巴林",
    "SAUDI": "沙烏地阿拉伯",
    "JEDDAH": "吉達",
    "AUSTRALIAN": "澳洲",
    "CHINESE": "中國",
    "MONACO": "摩納哥",
    "SPANISH": "西班牙",
    "CANADIAN": "加拿大",
    "AUSTRIAN": "奧地利",
    "BELGIAN": "比利時",
    "HUNGARIAN": "匈牙利",
    "DUTCH": "荷蘭",
    "ITALIAN": "義大利",
    "AZERBAIJAN": "亞塞拜然",
    "SINGAPORE": "新加坡",
    "UNITED STATES": "美國",
    "MEXICO CITY": "墨西哥城",
    "MEXICAN": "墨西哥",
    "SAO PAULO": "聖保羅",
    "SÃO PAULO": "聖保羅",
    "LAS VEGAS": "拉斯維加斯",
    "QATAR": "卡達",
    "ABU DHABI": "阿布達比",
    "YAS MARINA": "亞斯碼頭",
    "MADRID": "馬德里",
}


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


def _normalize_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _translate_country(country_name: Optional[str]) -> str:
    country = _normalize_text(country_name)
    return COUNTRY_ZH_MAP.get(country, country)


def _translate_circuit(circuit_short_name: Optional[str]) -> str:
    circuit = _normalize_text(circuit_short_name)
    return CIRCUIT_ZH_MAP.get(circuit, circuit)


def _extract_name_from_official_name(official_name: Optional[str]) -> str:
    """
    從官方長名稱中抓可用的中文地名或站名關鍵字。
    例如：
    FORMULA 1 CRYPTO.COM MIAMI GRAND PRIX 2026
    -> 邁阿密大獎賽
    """
    official = _normalize_text(official_name).upper()
    if not official:
        return ""

    official = re.sub(r"\s+\d{4}$", "", official).strip()

    for keyword, zh_name in OFFICIAL_NAME_KEYWORD_MAP.items():
        if keyword in official:
            # 如果是國家名關鍵字，就直接輸出「XX大獎賽」
            if zh_name in COUNTRY_ZH_MAP.values():
                return f"{zh_name}大獎賽"
            return f"{zh_name}大獎賽"

    # 萬一都抓不到，就試著抓 "... GRAND PRIX"
    match = re.search(r"([A-Z][A-Z\s]+?)\s+GRAND PRIX", official)
    if match:
        raw_name = match.group(1).strip().title()
        return f"{raw_name} 大獎賽"

    return ""


def _build_chinese_meeting_name(
    country_name: Optional[str],
    circuit_short_name: Optional[str],
    meeting_name: Optional[str],
    meeting_official_name: Optional[str],
) -> str:
    """
    建立中文版站名，優先產出你要的格式：
    - 美國邁阿密大獎賽
    - 英國銀石大獎賽
    """
    country_en = _normalize_text(country_name)
    circuit_en = _normalize_text(circuit_short_name)

    # 1. 特例優先
    special = SPECIAL_MEETING_NAME_MAP.get((country_en, circuit_en))
    if special:
        return special

    # 2. 一般 country + circuit 組法
    country_zh = _translate_country(country_en)
    circuit_zh = _translate_circuit(circuit_en)

    if country_zh and circuit_zh:
        # 避免像「摩納哥摩納哥大獎賽」這種重複
        if country_zh == circuit_zh:
            return f"{country_zh}大獎賽"
        return f"{country_zh}{circuit_zh}大獎賽"

    # 3. 若有 session/meeting name，可嘗試轉中文但這通常是英文短名
    cleaned_meeting_name = _normalize_text(meeting_name)
    if cleaned_meeting_name:
        # 常見 "Miami Grand Prix" 這種
        lower_name = cleaned_meeting_name.lower()

        for circuit_key, circuit_zh_value in CIRCUIT_ZH_MAP.items():
            if circuit_key.lower() in lower_name and country_zh:
                if country_zh == circuit_zh_value:
                    return f"{country_zh}大獎賽"
                return f"{country_zh}{circuit_zh_value}大獎賽"

        for country_key, country_zh_value in COUNTRY_ZH_MAP.items():
            if country_key.lower() in lower_name:
                return f"{country_zh_value}大獎賽"

    # 4. 再從 official name 抽關鍵字
    official_guess = _extract_name_from_official_name(meeting_official_name)
    if official_guess:
        # 如果 official_guess 只有地名，且 country_zh 存在，補成「國家 + 地名」
        if country_zh and not official_guess.startswith(country_zh):
            raw = official_guess.replace("大獎賽", "").strip()
            if raw and raw != country_zh:
                return f"{country_zh}{raw}大獎賽"
        return official_guess

    # 5. 最後 fallback
    if country_zh:
        return f"{country_zh}大獎賽"
    if circuit_zh:
        return f"{circuit_zh}大獎賽"

    return "未知大獎賽"


def fetch_meetings_meta_for_year(year: int) -> dict[int, dict]:
    """
    取得年度 meetings 資料，建立 meeting_key -> metadata 對照表。
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

        # 過濾掉測試賽
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

        if resolved_meeting_name == "未知大獎賽":
            resolved_meeting_name = meta.get("meeting_name", "未知大獎賽")

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
            if (
                meetings_map[mk].meeting_name in ("Unknown GP", "未知大獎賽")
                and session.meeting_name not in ("Unknown GP", "未知大獎賽")
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