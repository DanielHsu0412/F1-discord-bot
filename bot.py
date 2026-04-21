"""
bot.py — F1 Taiwan Info Discord Bot 主程式

功能（MVP 版本）：
  ✅ 賽前總通知 Embed（每站大獎賽前 3 天自動發送）
  ✅ 台灣時間轉換（Asia/Taipei GMT+8）
  ✅ Sprint / 非 Sprint 週末自動判斷

使用方式：
  1. 複製 .env.example → .env，填入 DISCORD_TOKEN 與 CHANNEL_ID
  2. pip install -r requirements.txt
  3. python bot.py

指令：
  公開指令：
    !f1 status    — 顯示下一站資訊
    !f1 next      — 顯示下一站完整賽程 Embed（立即發送，不記錄）

  管理員指令：
    !f1 force     — 強制重新發送下一站賽前通知（會覆蓋記錄）
    !f1 log       — 顯示已發送記錄
"""

import logging
import sys
from datetime import datetime, timezone

import discord
from discord.ext import tasks

from config import (
    DISCORD_TOKEN,
    CHANNEL_ID,
    CHECK_INTERVAL_MINUTES,
    validate_config,
)
from modules.scheduler import check_and_send_notifications, force_send_pre_race, get_sent_log
from modules.f1_data import get_current_year_meetings, get_upcoming_meetings
from modules.embed_builder import build_pre_race_embed
from modules.timezone_utils import to_taipei, format_time

logger = logging.getLogger(__name__)

# ── Discord Client 設定 ───────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True  # 需要讀取訊息內容（用於文字指令）

client = discord.Client(intents=intents)


# ── Bot 事件處理 ──────────────────────────────────────────────

@client.event
async def on_ready() -> None:
    """Bot 成功登入後的初始化。"""
    logger.info(f"✅ Bot 已登入：{client.user} (ID: {client.user.id})")
    logger.info(f"📡 監聽頻道 ID：{CHANNEL_ID}")

    # 啟動定時排程
    if not check_loop.is_running():
        check_loop.start()
        logger.info(f"⏱️ 排程啟動，每 {CHECK_INTERVAL_MINUTES} 分鐘檢查一次")


@client.event
async def on_message(message: discord.Message) -> None:
    """處理 Bot 指令。"""
    # 忽略 Bot 自身訊息
    if message.author.bot:
        return

    # 只回應 !f1 開頭的指令
    if not message.content.startswith("!f1"):
        return

    parts = message.content.strip().split()
    command = parts[1].lower() if len(parts) > 1 else "help"

    # 所有人可用的公開指令
    public_commands = {"status", "next", "help"}

    # 僅管理員可用的指令
    admin_commands = {"force", "log"}

    if command in public_commands:
        if command == "status":
            await cmd_status(message)
        elif command == "next":
            await cmd_next(message)
        else:
            await message.reply(
                "**F1 Taiwan Bot 指令**\n"
                "`!f1 status` — 查看下一站資訊\n"
                "`!f1 next`   — 立即預覽下一站賽程 Embed\n"
                "`!f1 force`  — 強制重送下一站賽前通知（管理員）\n"
                "`!f1 log`    — 查看已發送記錄（管理員）"
            )
        return

    if command in admin_commands:
        if not message.author.guild_permissions.administrator:
            await message.reply("❌ 此指令僅限管理員使用。")
            return

        if command == "force":
            await cmd_force(message)
        elif command == "log":
            await cmd_log(message)
        return

    await message.reply(
        "**F1 Taiwan Bot 指令**\n"
        "`!f1 status` — 查看下一站資訊\n"
        "`!f1 next`   — 立即預覽下一站賽程 Embed\n"
        "`!f1 force`  — 強制重送下一站賽前通知（管理員）\n"
        "`!f1 log`    — 查看已發送記錄（管理員）"
    )


# ── 指令實作 ─────────────────────────────────────────────────

async def cmd_status(message: discord.Message) -> None:
    """顯示下一站資訊。"""
    try:
        meetings = get_current_year_meetings()
        upcoming = get_upcoming_meetings(meetings)
        now_utc = datetime.now(tz=timezone.utc)

        if not upcoming:
            await message.reply("本季賽程已結束，或目前無可用資料。")
            return

        next_meeting = upcoming[0]
        race = next_meeting.race_session
        days_left = (race.date_start - now_utc).days if race else "?"
        sprint_label = "⚡ Sprint 週末" if next_meeting.is_sprint_weekend else "🔵 一般週末"
        race_tw = format_time(to_taipei(race.date_start)) if race else "未知"

        await message.reply(
            f"**下一站：{next_meeting.meeting_name}**\n"
            f"{sprint_label}\n"
            f"🏁 正賽（台灣時間）：{race_tw}\n"
            f"📅 距正賽：{days_left} 天"
        )
    except Exception as e:
        logger.error(f"cmd_status 錯誤：{e}")
        await message.reply(f"❌ 取得狀態時發生錯誤：{e}")


async def cmd_next(message: discord.Message) -> None:
    """立即在當前頻道預覽下一站賽程 Embed（不記錄為已發送）。"""
    try:
        meetings = get_current_year_meetings()
        upcoming = get_upcoming_meetings(meetings)

        if not upcoming:
            await message.reply("⚠️ 目前沒有即將到來的大獎賽。")
            return

        next_meeting = upcoming[0]
        embed = build_pre_race_embed(next_meeting)
        await message.channel.send(embed=embed)

    except Exception as e:
        logger.error(f"cmd_next 錯誤：{e}")
        await message.reply(f"❌ 發生錯誤：{e}")


async def cmd_force(message: discord.Message) -> None:
    """強制重新發送下一站賽前通知到指定頻道（覆蓋已發送記錄）。"""
    try:
        meetings = get_current_year_meetings()
        upcoming = get_upcoming_meetings(meetings)

        if not upcoming:
            await message.reply("⚠️ 沒有即將到來的大獎賽。")
            return

        next_meeting = upcoming[0]
        channel = client.get_channel(CHANNEL_ID)
        if channel is None:
            await message.reply(f"❌ 找不到頻道 ID {CHANNEL_ID}")
            return

        # 先移除舊記錄，再強制發送
        sent_log = get_sent_log()
        from modules.sent_log import SentLog
        key = SentLog.pre_race_key(next_meeting.year, next_meeting.meeting_key)
        sent_log.remove(key)

        success = await force_send_pre_race(channel, next_meeting)
        if success:
            await message.reply(f"✅ 已強制發送：{next_meeting.meeting_name} 賽前通知")
        else:
            await message.reply("❌ 強制發送失敗，請查看 Log")

    except Exception as e:
        logger.error(f"cmd_force 錯誤：{e}")
        await message.reply(f"❌ 發生錯誤：{e}")


async def cmd_log(message: discord.Message) -> None:
    """顯示最近 15 筆已發送記錄。"""
    sent_log = get_sent_log()
    all_records = sent_log.get_all()

    if not all_records:
        await message.reply("📋 目前沒有任何發送記錄。")
        return

    lines = [f"📋 **已發送記錄（共 {len(all_records)} 筆）**"]
    for key, value in list(all_records.items())[-15:]:
        lines.append(f"`{key}` → {value}")

    await message.reply("\n".join(lines))


# ── 定時排程 Task ─────────────────────────────────────────────

@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_loop() -> None:
    """每 N 分鐘執行一次通知檢查。"""
    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        logger.error(f"找不到頻道 {CHANNEL_ID}，請確認 CHANNEL_ID 設定正確")
        return

    try:
        await check_and_send_notifications(channel)
    except Exception as e:
        logger.error(f"排程執行錯誤（不影響下次執行）：{e}", exc_info=True)


@check_loop.before_loop
async def before_check_loop() -> None:
    """等待 Bot 完全就緒後才啟動排程。"""
    await client.wait_until_ready()
    logger.info("排程就緒，開始首次檢查...")


@check_loop.error
async def check_loop_error(error: Exception) -> None:
    """排程錯誤處理（防止 Loop 中斷）。"""
    logger.error(f"排程發生未捕獲錯誤：{error}", exc_info=True)


# ── 程式進入點 ────────────────────────────────────────────────

if __name__ == "__main__":
    # 驗證設定
    try:
        validate_config()
    except ValueError as e:
        print(f"❌ 設定錯誤，Bot 無法啟動：\n{e}")
        sys.exit(1)

    logger.info("🏎️  F1 Taiwan Info Discord Bot 啟動中...")

    try:
        client.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("❌ Discord Token 無效！請重新確認 .env 的 DISCORD_TOKEN")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot 已手動停止")