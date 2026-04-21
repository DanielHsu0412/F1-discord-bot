"""
modules/scheduler.py — 通知排程模組（Scheduler Module）

每 5 分鐘被 Bot 呼叫一次，決定是否需要發送通知。
"""

import logging
from datetime import datetime, timezone, timedelta

import discord

from config import PRE_RACE_NOTIFY_DAYS, PRE_SESSION_NOTIFY_MINUTES
from modules.f1_data import F1Meeting, get_current_year_meetings, get_upcoming_meetings
from modules.embed_builder import build_pre_race_embed, build_session_reminder_embed
from modules.sent_log import SentLog

logger = logging.getLogger(__name__)

# 全域 SentLog 實例（Bot 啟動時初始化一次）
_sent_log: SentLog | None = None


def get_sent_log() -> SentLog:
    """取得（或初始化）SentLog 單例。"""
    global _sent_log
    if _sent_log is None:
        _sent_log = SentLog()
    return _sent_log


# ── 核心排程邏輯 ───────────────────────────────────────────────

async def check_and_send_notifications(channel: discord.TextChannel) -> None:
    """
    主排程函式。每 5 分鐘由 Bot 呼叫。

    流程：
    1. 取得年度賽程
    2. 過濾出未來的大獎賽
    3. 檢查是否需要發送「賽前總通知」
    4. 檢查是否需要發送「單場提醒」
    """
    logger.info("開始排程檢查...")
    sent_log = get_sent_log()
    now = datetime.now(tz=timezone.utc)

    # 1. 取得賽程
    try:
        meetings = get_current_year_meetings()
    except Exception as e:
        logger.error(f"取得賽程失敗：{e}")
        return

    if not meetings:
        logger.warning("賽程資料為空，跳過本次檢查")
        return

    upcoming = get_upcoming_meetings(meetings)
    logger.info(f"找到 {len(upcoming)} 站未來大獎賽")

    for meeting in upcoming:
        await _check_pre_race_notification(channel, meeting, sent_log, now)
        await _check_session_reminders(channel, meeting, sent_log, now)

    logger.info("排程檢查完畢")


async def _check_pre_race_notification(
    channel: discord.TextChannel,
    meeting: F1Meeting,
    sent_log: SentLog,
    now: datetime,
) -> None:
    """
    賽前總通知檢查。
    條件：正賽距現在 ≤ PRE_RACE_NOTIFY_DAYS 天，且尚未發送。
    """
    race = meeting.race_session
    if race is None:
        return

    key = SentLog.pre_race_key(meeting.year, meeting.meeting_key)
    if sent_log.is_sent(key):
        return  # 已發送，跳過

    days_until_race = (race.date_start - now).total_seconds() / 86400
    if days_until_race < 0:
        return  # 正賽已過
    if days_until_race > PRE_RACE_NOTIFY_DAYS:
        return  # 還不到觸發時間

    logger.info(f"觸發賽前通知：{meeting.meeting_name}（距正賽 {days_until_race:.1f} 天）")

    try:
        embed = build_pre_race_embed(meeting)
        await channel.send(embed=embed)
        sent_log.mark_sent(key, note=f"{meeting.meeting_name} 賽前通知")
        logger.info(f"✅ 已發送賽前通知：{meeting.meeting_name}")
    except discord.DiscordException as e:
        logger.error(f"發送 Discord 訊息失敗：{e}")
    except Exception as e:
        logger.error(f"未知錯誤（賽前通知）：{e}")


async def _check_session_reminders(
    channel: discord.TextChannel,
    meeting: F1Meeting,
    sent_log: SentLog,
    now: datetime,
) -> None:
    """
    單場提醒檢查。
    條件：session 距現在 ≤ PRE_SESSION_NOTIFY_MINUTES 分鐘，且尚未發送。
    """
    for session in meeting.sessions_needing_reminder():
        key = SentLog.reminder_key(meeting.year, meeting.meeting_key, session.session_key)
        if sent_log.is_sent(key):
            continue

        minutes_until = (session.date_start - now).total_seconds() / 60
        if minutes_until < 0:
            continue  # 已過
        if minutes_until > PRE_SESSION_NOTIFY_MINUTES:
            continue  # 還不到觸發時間

        logger.info(
            f"觸發單場提醒：{meeting.meeting_name} {session.session_name}"
            f"（距開始 {minutes_until:.0f} 分鐘）"
        )

        try:
            from modules.embed_builder import build_session_reminder_embed
            embed = build_session_reminder_embed(meeting, session)
            await channel.send(embed=embed)
            sent_log.mark_sent(key, note=f"{meeting.meeting_name} {session.session_name} 提醒")
            logger.info(f"✅ 已發送單場提醒：{meeting.meeting_name} {session.session_name}")
        except discord.DiscordException as e:
            logger.error(f"發送 Discord 訊息失敗：{e}")
        except Exception as e:
            logger.error(f"未知錯誤（單場提醒）：{e}")


# ── 工具方法（供管理員指令使用） ───────────────────────────────

async def force_send_pre_race(channel: discord.TextChannel, meeting: F1Meeting) -> bool:
    """
    強制發送指定大獎賽的賽前通知（忽略已發送記錄）。
    供 /force 管理員指令使用。
    """
    try:
        embed = build_pre_race_embed(meeting)
        await channel.send(embed=embed)
        sent_log = get_sent_log()
        key = SentLog.pre_race_key(meeting.year, meeting.meeting_key)
        sent_log.mark_sent(key, note=f"{meeting.meeting_name} 賽前通知（強制）")
        return True
    except Exception as e:
        logger.error(f"強制發送失敗：{e}")
        return False
