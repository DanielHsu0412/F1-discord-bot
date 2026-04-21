"""
modules/sent_log.py — 已發送記錄模組

防止重複發送，支援 Bot 重啟後恢復。
資料儲存於 JSON 檔案。
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from config import SENT_LOG_FILE

logger = logging.getLogger(__name__)


class SentLog:
    """
    管理已發送通知的記錄。

    Key 格式：
        賽前通知：  "{year}_{meeting_key}_pre_race"
        單場提醒：  "{year}_{meeting_key}_{session_key}_reminder"
        賽後結果：  "{year}_{meeting_key}_result"
    """

    def __init__(self, filepath: str = SENT_LOG_FILE):
        self.filepath = filepath
        self._log: dict[str, str] = {}  # key → ISO timestamp（何時發送）
        self._load()

    # ── 私有方法 ──────────────────────────────────────────────

    def _load(self) -> None:
        """從 JSON 檔案載入記錄。"""
        if not os.path.exists(self.filepath):
            logger.info(f"送出記錄檔 '{self.filepath}' 不存在，從空白開始")
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._log = json.load(f)
            logger.info(f"已載入 {len(self._log)} 筆送出記錄")
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"載入記錄檔失敗：{e}，重置為空白")
            self._log = {}

    def _save(self) -> None:
        """將記錄寫入 JSON 檔案。"""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self._log, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"寫入記錄檔失敗：{e}")

    # ── Key 生成方法 ──────────────────────────────────────────

    @staticmethod
    def pre_race_key(year: int, meeting_key: int) -> str:
        return f"{year}_{meeting_key}_pre_race"

    @staticmethod
    def reminder_key(year: int, meeting_key: int, session_key: int) -> str:
        return f"{year}_{meeting_key}_{session_key}_reminder"

    @staticmethod
    def result_key(year: int, meeting_key: int) -> str:
        return f"{year}_{meeting_key}_result"

    # ── 公開方法 ──────────────────────────────────────────────

    def is_sent(self, key: str) -> bool:
        """檢查指定 key 是否已發送。"""
        return key in self._log

    def mark_sent(self, key: str, note: str = "") -> None:
        """
        標記 key 為已發送。

        Args:
            key:  記錄的 key
            note: 說明（如 GP 名稱 + 類型），便於人工查看記錄檔
        """
        timestamp = datetime.utcnow().isoformat() + "Z"
        self._log[key] = f"{timestamp} | {note}" if note else timestamp
        self._save()
        logger.info(f"[SentLog] 已記錄：{key} ({note})")

    def get_all(self) -> dict[str, str]:
        """回傳全部記錄（供除錯或管理指令使用）。"""
        return dict(self._log)

    def remove(self, key: str) -> bool:
        """手動移除某筆記錄（供管理員強制重送使用）。"""
        if key in self._log:
            del self._log[key]
            self._save()
            logger.info(f"[SentLog] 已移除記錄：{key}")
            return True
        return False

    def clear_year(self, year: int) -> int:
        """清除特定年份的所有記錄（新賽季重置用）。"""
        keys_to_remove = [k for k in self._log if k.startswith(f"{year}_")]
        for k in keys_to_remove:
            del self._log[k]
        self._save()
        logger.info(f"已清除 {len(keys_to_remove)} 筆 {year} 年記錄")
        return len(keys_to_remove)
