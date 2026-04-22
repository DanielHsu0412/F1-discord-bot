"""
bot.py — F1 Taiwan Info Discord Bot 主程式

互動方式：
- 打 !f1 叫出按鈕主選單
- 按按鈕後，Bot 會先顯示資訊，再自動補一個新的按鈕面板在下面
- 這樣使用者可以一直按，不用一直重新打指令

公開功能：
- Next Race
- Results
- Drivers (官方連結)
- Constructors / Teams (官方連結)
- Race Information（暫時 coming soon）

管理員功能：
- Force Notify
- Show Logs
"""

import logging
import sys
from datetime import datetime, timezone

import discord
from discord.ext import tasks
from discord.ui import View, Button

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
    fetch_race_results_history,
)
from modules.embed_builder import build_pre_race_embed
from modules.timezone_utils import to_taipei, format_time

logger = logging.getLogger(__name__)

# ── Discord Client 設定 ───────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


# ── 共用 UI / 輸出 Helper ────────────────────────────────────

def build_main_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🏎️ F1 Taiwan Bot",
        description="請選擇功能👇",
        color=discord.Color.red(),
    )
    embed.set_footer(text="F1 Taiwan Bot")
    return embed


async def send_main_menu(channel: discord.abc.Messageable) -> None:
    await channel.send(embed=build_main_menu_embed(), view=F1MainMenu())


async def send_status_to_channel(channel: discord.abc.Messageable) -> None:
    meetings = get_current_year_meetings()
    upcoming = get_upcoming_meetings(meetings)
    now_utc = datetime.now(tz=timezone.utc)

    if not upcoming:
        await channel.send("No upcoming Grand Prix found.")
        return

    next_meeting = upcoming[0]
    race = next_meeting.race_session
    days_left = (race.date_start - now_utc).days if race else "?"
    sprint_label = "⚡ Sprint weekend" if next_meeting.is_sprint_weekend else "🔵 Normal weekend"
    race_tw = format_time(to_taipei(race.date_start)) if race else "Unknown"

    await channel.send(
        f"**Next race: {next_meeting.meeting_name}**\n"
        f"{sprint_label}\n"
        f"🏁 Race time (Taiwan): {race_tw}\n"
        f"📅 Days to race: {days_left}"
    )


async def send_next_embed_to_channel(channel: discord.abc.Messageable) -> None:
    meetings = get_current_year_meetings()
    upcoming = get_upcoming_meetings(meetings)

    if not upcoming:
        await channel.send("⚠️ No upcoming Grand Prix found.")
        return

    next_meeting = upcoming[0]
    embed = build_pre_race_embed(next_meeting)
    await channel.send(embed=embed)


async def send_drivers_link_to_channel(channel: discord.abc.Messageable) -> None:
    embed = discord.Embed(
        title="🏎️ Drivers' Standings",
        description="👉 [Click here to view latest standings](https://www.formula1.com/en/results.html/2026/drivers.html)",
        color=discord.Color.red(),
    )
    embed.set_footer(text="Data from Formula1.com")
    await channel.send(embed=embed)


async def send_constructors_link_to_channel(channel: discord.abc.Messageable) -> None:
    embed = discord.Embed(
        title="🏁 Constructors' Standings",
        description="👉 [Click here to view latest standings](https://www.formula1.com/en/results.html/2026/team.html)",
        color=discord.Color.blue(),
    )
    embed.set_footer(text="Data from Formula1.com")
    await channel.send(embed=embed)


async def send_results_to_channel(channel: discord.abc.Messageable) -> None:
    results = fetch_race_results_history()
    if not results:
        await channel.send("⚠️ Could not fetch race results.")
        return

    embed = discord.Embed(
        title="🏁 2026 Race Results",
        color=discord.Color.gold(),
    )

    lines = []
    for r in results:
        lines.append(
            f"**{r.grand_prix}** ({r.date_label}) — {r.winner} ｜{r.team}"
        )

    embed.description = "\n".join(lines[:20])
    embed.set_footer(text="F1 Taiwan Bot")
    await channel.send(embed=embed)


async def send_help_to_channel(channel: discord.abc.Messageable) -> None:
    await channel.send(
        "**F1 Taiwan Bot Commands**\n"
        "`!f1`               — Open main menu buttons\n"
        "`!f1 status`        — Show next race info\n"
        "`!f1 next`          — Preview next race weekend embed\n"
        "`!f1 drivers`       — Open official drivers' standings\n"
        "`!f1 constructors`  — Open official constructors' standings\n"
        "`!f1 teams`         — Same as constructors\n"
        "`!f1 results`       — Show 2026 race winners so far\n"
        "`!f1 force`         — Force send next race notification (admin)\n"
        "`!f1 log`           — Show sent logs (admin)"
    )


# ── 按鈕主選單 ────────────────────────────────────────────────

class F1MainMenu(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Next Race",
        style=discord.ButtonStyle.green,
        emoji="🔜",
        custom_id="f1_menu_next_race",
    )
    async def next_race(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await send_next_embed_to_channel(interaction.channel)
        await send_main_menu(interaction.channel)

    @discord.ui.button(
        label="Results",
        style=discord.ButtonStyle.blurple,
        emoji="🏁",
        custom_id="f1_menu_results",
    )
    async def results(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await send_results_to_channel(interaction.channel)
        await send_main_menu(interaction.channel)

    @discord.ui.button(
        label="Drivers",
        style=discord.ButtonStyle.secondary,
        emoji="📊",
        custom_id="f1_menu_drivers",
    )
    async def drivers(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await send_drivers_link_to_channel(interaction.channel)
        await send_main_menu(interaction.channel)

    @discord.ui.button(
        label="Teams",
        style=discord.ButtonStyle.secondary,
        emoji="🏎️",
        custom_id="f1_menu_teams",
    )
    async def teams(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await send_constructors_link_to_channel(interaction.channel)
        await send_main_menu(interaction.channel)

    @discord.ui.button(
        label="Race Info",
        style=discord.ButtonStyle.danger,
        emoji="📍",
        custom_id="f1_menu_race_info",
    )
    async def race_info(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await interaction.channel.send("🚧 Race Information selector coming soon.")
        await send_main_menu(interaction.channel)

    @discord.ui.button(
        label="Status",
        style=discord.ButtonStyle.primary,
        emoji="ℹ️",
        row=1,
        custom_id="f1_menu_status",
    )
    async def status(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await send_status_to_channel(interaction.channel)
        await send_main_menu(interaction.channel)

    @discord.ui.button(
        label="Help",
        style=discord.ButtonStyle.secondary,
        emoji="❓",
        row=1,
        custom_id="f1_menu_help",
    )
    async def help_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await send_help_to_channel(interaction.channel)
        await send_main_menu(interaction.channel)

    @discord.ui.button(
        label="Force Notify",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
        row=1,
        custom_id="f1_menu_force_notify",
    )
    async def force_notify(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ This button is admin only.", ephemeral=True)
            return

        await interaction.response.defer()
        await force_send_command_to_channel(interaction.channel)
        await send_main_menu(interaction.channel)

    @discord.ui.button(
        label="Show Logs",
        style=discord.ButtonStyle.secondary,
        emoji="📋",
        row=1,
        custom_id="f1_menu_show_logs",
    )
    async def show_logs(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ This button is admin only.", ephemeral=True)
            return

        await interaction.response.defer()
        await send_logs_to_channel(interaction.channel)
        await send_main_menu(interaction.channel)


# ── Bot 事件處理 ──────────────────────────────────────────────

@client.event
async def on_ready() -> None:
    """Bot 成功登入後的初始化。"""
    logger.info(f"✅ Bot 已登入：{client.user} (ID: {client.user.id})")
    logger.info(f"📡 監聽頻道 ID：{CHANNEL_ID}")

    # 註冊 persistent view，讓重啟後舊按鈕仍能生效
    try:
        client.add_view(F1MainMenu())
    except Exception as e:
        logger.warning(f"add_view 失敗：{e}")

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
    command = parts[1].lower() if len(parts) > 1 else "menu"

    public_commands = {
        "menu", "status", "next", "drivers", "constructors", "teams", "results", "help"
    }
    admin_commands = {"force", "log"}

    if command in public_commands:
        if command == "menu":
            await send_main_menu(message.channel)
        elif command == "status":
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
    await send_help_to_channel(message.channel)


async def cmd_status(message: discord.Message) -> None:
    try:
        await send_status_to_channel(message.channel)
    except Exception as e:
        logger.error(f"cmd_status 錯誤：{e}", exc_info=True)
        await message.reply(f"❌ Failed to get status: {e}")


async def cmd_next(message: discord.Message) -> None:
    try:
        await send_next_embed_to_channel(message.channel)
    except Exception as e:
        logger.error(f"cmd_next 錯誤：{e}", exc_info=True)
        await message.reply(f"❌ Failed: {e}")


async def cmd_drivers(message: discord.Message) -> None:
    await send_drivers_link_to_channel(message.channel)


async def cmd_constructors(message: discord.Message) -> None:
    await send_constructors_link_to_channel(message.channel)


async def cmd_results(message: discord.Message) -> None:
    try:
        await send_results_to_channel(message.channel)
    except Exception as e:
        logger.error(f"cmd_results 錯誤：{e}", exc_info=True)
        await message.reply(f"❌ Failed to get race results: {e}")


async def force_send_command_to_channel(channel: discord.abc.Messageable) -> None:
    meetings = get_current_year_meetings()
    upcoming = get_upcoming_meetings(meetings)

    if not upcoming:
        await channel.send("⚠️ No upcoming Grand Prix.")
        return

    next_meeting = upcoming[0]
    target_channel = client.get_channel(CHANNEL_ID)
    if target_channel is None:
        await channel.send(f"❌ Channel ID {CHANNEL_ID} not found")
        return

    sent_log = get_sent_log()
    from modules.sent_log import SentLog
    key = SentLog.pre_race_key(next_meeting.year, next_meeting.meeting_key)
    sent_log.remove(key)

    success = await force_send_pre_race(target_channel, next_meeting)
    if success:
        await channel.send(f"✅ Force sent: {next_meeting.meeting_name}")
    else:
        await channel.send("❌ Force send failed. Check logs.")


async def cmd_force(message: discord.Message) -> None:
    try:
        await force_send_command_to_channel(message.channel)
    except Exception as e:
        logger.error(f"cmd_force 錯誤：{e}", exc_info=True)
        await message.reply(f"❌ Failed: {e}")


async def send_logs_to_channel(channel: discord.abc.Messageable) -> None:
    sent_log = get_sent_log()
    all_records = sent_log.get_all()

    if not all_records:
        await channel.send("📋 No sent logs yet.")
        return

    lines = [f"📋 **Sent logs ({len(all_records)})**"]
    for key, value in list(all_records.items())[-15:]:
        lines.append(f"`{key}` → {value}")

    await channel.send("\n".join(lines))


async def cmd_log(message: discord.Message) -> None:
    await send_logs_to_channel(message.channel)


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