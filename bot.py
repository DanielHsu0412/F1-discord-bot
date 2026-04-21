"""
bot.py — F1 Taiwan Info Discord Bot 主程式

公開指令：
  !f1 status
  !f1 next
  !f1 drivers
  !f1 constructors
  !f1 teams
  !f1 results
  !f1 help

管理員指令：
  !f1 force
  !f1 log
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
from modules.f1_data import (
    get_current_year_meetings,
    get_upcoming_meetings,
    fetch_driver_standings,
    fetch_team_standings,
    fetch_race_results_history,
)
from modules.embed_builder import build_pre_race_embed
from modules.timezone_utils import to_taipei, format_time

logger = logging.getLogger(__name__)

# ── Discord Client 設定 ───────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


# ── Bot 事件處理 ──────────────────────────────────────────────

@client.event
async def on_ready() -> None:
    """Bot 成功登入後的初始化。"""
    logger.info(f"✅ Bot 已登入：{client.user} (ID: {client.user.id})")
    logger.info(f"📡 監聽頻道 ID：{CHANNEL_ID}")

    if not check_loop.is_running():
        check_loop.start()
        logger.info(f"⏱️ 排程啟動，每 {CHECK_INTERVAL_MINUTES} 分鐘檢查一次")


@client.event
async def on_message(message: discord.Message) -> None:
    """處理 Bot 指令。"""
    if message.author.bot:
        return

    if not message.content.startswith("!f1"):
        return

    parts = message.content.strip().split()
    command = parts[1].lower() if len(parts) > 1 else "help"

    public_commands = {"status", "next", "drivers", "constructors", "teams", "results", "help"}
    admin_commands = {"force", "log"}

    if command in public_commands:
        if command == "status":
            await cmd_status(message)
        elif command == "next":
            await cmd_next(message)
        elif command == "drivers":
            await cmd_drivers(message)
        elif command in {"constructors", "teams"}:
            await cmd_constructors(message)
        elif command == "results":
            await cmd_results(message)
        else:
            await cmd_help(message)
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

    await cmd_help(message)


# ── 指令實作 ─────────────────────────────────────────────────

async def cmd_help(message: discord.Message) -> None:
    await message.reply(
        "**F1 Taiwan Bot Commands**\n"
        "`!f1 status`        — Show next race info\n"
        "`!f1 next`          — Preview next race weekend embed\n"
        "`!f1 drivers`       — Show latest drivers' standings\n"
        "`!f1 constructors`  — Show latest constructors' standings\n"
        "`!f1 teams`         — Same as constructors\n"
        "`!f1 results`       — Show 2026 race winners so far\n"
        "`!f1 force`         — Force send next race notification (admin)\n"
        "`!f1 log`           — Show sent logs (admin)"
    )


async def cmd_status(message: discord.Message) -> None:
    """顯示下一站資訊。"""
    try:
        meetings = get_current_year_meetings()
        upcoming = get_upcoming_meetings(meetings)
        now_utc = datetime.now(tz=timezone.utc)

        if not upcoming:
            await message.reply("No upcoming Grand Prix found.")
            return

        next_meeting = upcoming[0]
        race = next_meeting.race_session
        days_left = (race.date_start - now_utc).days if race else "?"
        sprint_label = "⚡ Sprint weekend" if next_meeting.is_sprint_weekend else "🔵 Normal weekend"
        race_tw = format_time(to_taipei(race.date_start)) if race else "Unknown"

        await message.reply(
            f"**Next race: {next_meeting.meeting_name}**\n"
            f"{sprint_label}\n"
            f"🏁 Race time (Taiwan): {race_tw}\n"
            f"📅 Days to race: {days_left}"
        )
    except Exception as e:
        logger.error(f"cmd_status 錯誤：{e}", exc_info=True)
        await message.reply(f"❌ Failed to get status: {e}")


async def cmd_next(message: discord.Message) -> None:
    """立即在當前頻道預覽下一站賽程 Embed（不記錄為已發送）。"""
    try:
        meetings = get_current_year_meetings()
        upcoming = get_upcoming_meetings(meetings)

        if not upcoming:
            await message.reply("⚠️ No upcoming Grand Prix found.")
            return

        next_meeting = upcoming[0]
        embed = build_pre_race_embed(next_meeting)
        await message.channel.send(embed=embed)

    except Exception as e:
        logger.error(f"cmd_next 錯誤：{e}", exc_info=True)
        await message.reply(f"❌ Failed: {e}")


async def cmd_drivers(message: discord.Message) -> None:
    embed = discord.Embed(
        title="🏎️ Drivers' Standings",
        description="👉 [Click here to view latest standings](https://www.formula1.com/en/results.html/2026/drivers.html)",
        color=discord.Color.red(),
    )
    embed.set_footer(text="Data from Formula1.com")
    await message.channel.send(embed=embed)


async def cmd_constructors(message: discord.Message) -> None:
    embed = discord.Embed(
        title="🏁 Constructors' Standings",
        description="👉 [Click here to view latest standings](https://www.formula1.com/en/results.html/2026/team.html)",
        color=discord.Color.blue(),
    )
    embed.set_footer(text="Data from Formula1.com")
    await message.channel.send(embed=embed)


async def cmd_results(message: discord.Message) -> None:
    """顯示本季各站正賽冠軍。"""
    try:
        results = fetch_race_results_history()
        if not results:
            await message.reply("⚠️ Could not fetch race results.")
            return

        embed = discord.Embed(
            title="🏁 2026 Race Results",
            color=discord.Color.gold(),
        )

        lines = []
        for r in results:
            lines.append(
                f"**{r.grand_prix}** — {r.winner} ｜{r.team}"
            )

        embed.description = "\n".join(lines[:20])
        embed.set_footer(text="F1 Taiwan Bot")
        await message.channel.send(embed=embed)

    except Exception as e:
        logger.error(f"cmd_results 錯誤：{e}", exc_info=True)
        await message.reply(f"❌ Failed to get race results: {e}")


async def cmd_force(message: discord.Message) -> None:
    """強制重新發送下一站賽前通知到指定頻道（覆蓋已發送記錄）。"""
    try:
        meetings = get_current_year_meetings()
        upcoming = get_upcoming_meetings(meetings)

        if not upcoming:
            await message.reply("⚠️ No upcoming Grand Prix.")
            return

        next_meeting = upcoming[0]
        channel = client.get_channel(CHANNEL_ID)
        if channel is None:
            await message.reply(f"❌ Channel ID {CHANNEL_ID} not found")
            return

        sent_log = get_sent_log()
        from modules.sent_log import SentLog
        key = SentLog.pre_race_key(next_meeting.year, next_meeting.meeting_key)
        sent_log.remove(key)

        success = await force_send_pre_race(channel, next_meeting)
        if success:
            await message.reply(f"✅ Force sent: {next_meeting.meeting_name}")
        else:
            await message.reply("❌ Force send failed. Check logs.")

    except Exception as e:
        logger.error(f"cmd_force 錯誤：{e}", exc_info=True)
        await message.reply(f"❌ Failed: {e}")


async def cmd_log(message: discord.Message) -> None:
    """顯示最近 15 筆已發送記錄。"""
    sent_log = get_sent_log()
    all_records = sent_log.get_all()

    if not all_records:
        await message.reply("📋 No sent logs yet.")
        return

    lines = [f"📋 **Sent logs ({len(all_records)})**"]
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