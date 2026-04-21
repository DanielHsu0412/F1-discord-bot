"""
config.py — 全域設定
從 .env 讀取環境變數，統一管理所有可調參數。
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

# ── Discord ──────────────────────────────────────────
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID: int = int(os.getenv("CHANNEL_ID", "0"))

# ── 通知時間設定 ──────────────────────────────────────
# 賽前總通知：幾天前發？
PRE_RACE_NOTIFY_DAYS: int = 3

# 單場提醒：幾分鐘前發？
PRE_SESSION_NOTIFY_MINUTES: int = 60

# 排程輪詢間隔（分鐘）
CHECK_INTERVAL_MINUTES: int = 5

# ── 資料來源 ──────────────────────────────────────────
OPENF1_BASE_URL: str = "https://api.openf1.org/v1"

# 請求 timeout（秒）
API_TIMEOUT: int = 15

# ── 儲存 ─────────────────────────────────────────────
SENT_LOG_FILE: str = "sent_log.json"

# ── 時區 ─────────────────────────────────────────────
TAIPEI_TZ_NAME: str = "Asia/Taipei"

# ── 日誌 ─────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def validate_config() -> None:
    """啟動時驗證必要設定是否存在。"""
    errors = []
    if not DISCORD_TOKEN:
        errors.append("DISCORD_TOKEN 未設定")
    if CHANNEL_ID == 0:
        errors.append("CHANNEL_ID 未設定或為 0")
    if errors:
        raise ValueError("設定錯誤：\n" + "\n".join(f"  - {e}" for e in errors))
