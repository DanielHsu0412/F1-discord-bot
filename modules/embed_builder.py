"""
modules/embed_builder.py — Discord Embed UI 模組

負責生成所有類型的 Discord Embed 訊息。
"""

import discord
from collections import defaultdict
from datetime import datetime, timezone
from modules.f1_data import F1Meeting, F1Session
from modules.timezone_utils import to_taipei, format_date_header, format_session_line, format_time

# ── 顏色定義 ──────────────────────────────────────────────────
COLOR_NORMAL_WEEKEND = discord.Color.from_rgb(0, 120, 215)   # 藍色（一般週末）
COLOR_SPRINT_WEEKEND = discord.Color.from_rgb(255, 102, 0)   # 橘色（Sprint 週末）
COLOR_SESSION_REMINDER = discord.Color.from_rgb(255, 215, 0) # 金色（單場提醒）
COLOR_RACE_RESULT = discord.Color.from_rgb(230, 0, 0)        # 紅色（賽後結果）

# ── Footer ────────────────────────────────────────────────────
FOOTER_TEXT = "F1 Taiwan Bot｜資料已轉換為台灣時間"
FOOTER_ICON = None  # 可設定 Bot 頭像 URL


def build_pre_race_embed(meeting: F1Meeting) -> discord.Embed:
    """
    賽前總通知 Embed（MVP 核心功能）。
    包含完整週末賽程，分天顯示，自動判斷 Sprint 週末。

    Args:
        meeting: F1Meeting 物件

    Returns:
        discord.Embed
    """
    is_sprint = meeting.is_sprint_weekend

    # ── 標題與顏色 ────────────────────────────────────────────
    color = COLOR_SPRINT_WEEKEND if is_sprint else COLOR_NORMAL_WEEKEND
    sprint_badge = "⚡ Sprint 週末" if is_sprint else ""

    embed = discord.Embed(
        title=f"🏁 {meeting.meeting_name}來啦！",
        description=(
            f"以下為**台灣時間（GMT+8）**\n"
            f"{sprint_badge}"
        ).strip(),
        color=color,
    )

    # ── 按天分組 sessions ─────────────────────────────────────
    days: dict[tuple, list[str]] = defaultdict(list)  # (date, date_obj) → [line, ...]

    for session in meeting.sorted_sessions:
        # 跳過未知 session 名稱
        if not session.display_name:
            continue

        dt_taipei = to_taipei(session.date_start)
        day_key = dt_taipei.date()

        line = format_session_line(session.display_name, dt_taipei)
        days[day_key].append(line)

    # ── 加入 Embed Fields ─────────────────────────────────────
    if not days:
        embed.add_field(
            name="⚠️ 資料尚未更新",
            value="賽程時間尚未公布，請稍後再查詢",
            inline=False,
        )
    else:
        for day_date in sorted(days.keys()):
            header = format_date_header(day_date)
            lines = days[day_date]
            embed.add_field(
                name=header,
                value="\n".join(lines),
                inline=False,
            )

    # ── Sprint 標注 ───────────────────────────────────────────
    if is_sprint:
        embed.add_field(
            name="\u200b",  # Zero-width space（空行分隔）
            value="⚡ 本站為 **Sprint 週末**，週六有 Sprint Qualifying + Sprint！",
            inline=False,
        )

    # ── Footer ────────────────────────────────────────────────
    embed.set_footer(text=FOOTER_TEXT)

    return embed


def build_session_reminder_embed(meeting: F1Meeting, session: F1Session) -> discord.Embed:
    """
    單場提醒 Embed（Qualifying / Race / Sprint / Sprint Qualifying）。
    在 session 開始前 1 小時發送。

    Args:
        meeting: F1Meeting 物件
        session: 即將開始的 F1Session

    Returns:
        discord.Embed
    """
    dt_taipei = to_taipei(session.date_start)
    time_str = format_time(dt_taipei)

    embed = discord.Embed(
        title="⏰ 比賽提醒",
        description=(
            f"**{meeting.meeting_name}** {session.display_name}\n"
            f"將在 **1 小時後**開始！"
        ),
        color=COLOR_SESSION_REMINDER,
    )

    embed.add_field(
        name="🕐 台灣時間",
        value=f"**{time_str}**",
        inline=True,
    )

    embed.add_field(
        name="📍 地點",
        value=f"{meeting.country_name}",
        inline=True,
    )

    embed.set_footer(text=FOOTER_TEXT)

    return embed


def build_race_result_embed(
    meeting: F1Meeting,
    p1: str,
    p2: str,
    p3: str,
    fastest_lap: str,
) -> discord.Embed:
    """
    賽後結果 Embed（第二版功能，預留介面）。

    Args:
        meeting:     F1Meeting 物件
        p1/p2/p3:   前三名車手姓名
        fastest_lap: 最快單圈車手

    Returns:
        discord.Embed
    """
    embed = discord.Embed(
        title=f"🏆 {meeting.meeting_name}完賽結果",
        color=COLOR_RACE_RESULT,
    )

    podium = f"🥇 {p1}\n🥈 {p2}\n🥉 {p3}"
    embed.add_field(name="頒獎台", value=podium, inline=False)
    embed.add_field(name="⚡ 最快單圈", value=fastest_lap, inline=False)

    embed.set_footer(text=FOOTER_TEXT)

    return embed


def build_error_embed(title: str, description: str) -> discord.Embed:
    """
    錯誤通知 Embed（供管理員除錯用，不對外發佈）。
    """
    embed = discord.Embed(
        title=f"⚠️ {title}",
        description=description,
        color=discord.Color.red(),
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed
