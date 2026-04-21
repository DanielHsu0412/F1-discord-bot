"""
modules/timezone_utils.py — 時區處理模組（Timezone Module）

將所有 UTC 時間轉換為台灣時間（Asia/Taipei，GMT+8）。
統一輸出格式：M/D（星期）HH:MM
"""

from datetime import datetime, date
import pytz

# 台北時區
TAIPEI_TZ = pytz.timezone("Asia/Taipei")

# 中文星期對照（weekday() 回傳 0=週一 … 6=週日）
WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


def to_taipei(dt: datetime) -> datetime:
    """
    將任何有時區資訊的 datetime 轉換為台北時間。

    Args:
        dt: 有 tzinfo 的 datetime（通常為 UTC）

    Returns:
        Asia/Taipei 時區的 datetime
    """
    if dt.tzinfo is None:
        # 沒有時區資訊時，假設為 UTC
        dt = pytz.utc.localize(dt)
    return dt.astimezone(TAIPEI_TZ)


def format_time(dt: datetime) -> str:
    """
    格式化為台灣時間顯示字串。

    Args:
        dt: 已轉換為台北時區的 datetime

    Returns:
        例：「5/3（五）00:30」
    """
    weekday = WEEKDAY_ZH[dt.weekday()]
    return f"{dt.month}/{dt.day}（{weekday}）{dt.strftime('%H:%M')}"


def format_date_header(d: date) -> str:
    """
    格式化日期為 Embed Field 標題。

    Args:
        d: date 物件

    Returns:
        例：「📅 5/3（五）」
    """
    weekday = WEEKDAY_ZH[d.weekday()]
    return f"📅 {d.month}/{d.day}（{weekday}）"


def format_session_line(display_name: str, dt_taipei: datetime) -> str:
    """
    格式化單行 session 資訊。

    Args:
        display_name: session 的顯示名稱（如 FP1、Qualifying）
        dt_taipei:    台北時區 datetime

    Returns:
        例：「FP1｜14:30」
    """
    return f"{display_name}｜{dt_taipei.strftime('%H:%M')}"


def get_taipei_now() -> datetime:
    """回傳現在的台北時間。"""
    return datetime.now(tz=TAIPEI_TZ)


def seconds_until(target_utc: datetime) -> float:
    """
    計算距離目標 UTC 時間還有幾秒。
    負數表示已過。
    """
    from datetime import timezone
    now = datetime.now(tz=timezone.utc)
    return (target_utc - now).total_seconds()


def minutes_until(target_utc: datetime) -> float:
    """計算距離目標 UTC 時間還有幾分鐘。"""
    return seconds_until(target_utc) / 60
