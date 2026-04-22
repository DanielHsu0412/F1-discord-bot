#  F1 Taiwan Info Discord Bot

自動整合 Formula 1 賽事資訊，以**台灣時間（GMT+8）**在 Discord 頻道發佈清晰易讀的 Embed 公告，專為台灣車迷設計。

---

##  功能（MVP 版本）

| 功能 | 說明 |
|------|------|
|  **賽前總通知** | 正賽前 3 天自動發送完整週末賽程 |
|  **台灣時間轉換** | 所有時間自動轉換為 Asia/Taipei（GMT+8）|
|  **Sprint 週末判斷** | 自動識別並以橘色標記 Sprint 週末 |
|  **單場提醒** | Qualifying / Race / Sprint 前 1 小時提醒 |
|  **防重複發送** | 記錄已發送通知，重啟後自動恢復 |

---

##  專案結構

```
f1-taiwan-bot/
├── bot.py                  # 主程式（Bot 進入點）
├── config.py               # 設定管理（讀取 .env）
├── modules/
│   ├── f1_data.py          # 資料來源模組（OpenF1 API）
│   ├── timezone_utils.py   # 時區轉換模組（UTC → GMT+8）
│   ├── embed_builder.py    # Discord Embed 建構模組
│   ├── scheduler.py        # 通知排程邏輯
│   └── sent_log.py         # 已發送記錄管理
├── sent_log.json           # 自動產生，記錄已發送通知
├── requirements.txt
├── .env                    # 你的設定（勿 commit！）
└── .env.example            # 設定範本
```

---

### 1. 建立 Discord Bot

1. 前往 [Discord Developer Portal](https://discord.com/developers/applications)
2. 建立新 Application → 進入 **Bot** 頁面
3. 點擊 **Reset Token** 取得 Bot Token
4. 在 **Privileged Gateway Intents** 啟用：
   - `MESSAGE CONTENT INTENT`
5. 在 **OAuth2 → URL Generator** 勾選：
   - Scope：`bot`
   - Permission：`Send Messages`、`Embed Links`、`View Channels`
6. 複製 URL 並邀請 Bot 到你的伺服器

### 2. 設定環境變數

```bash
cp .env.example .env
```

編輯 `.env`：

```env
DISCORD_TOKEN=你的Bot_Token
CHANNEL_ID=要發送公告的頻道ID
```

>  **如何取得頻道 ID？**  
> Discord → 設定 → 進階 → 開啟開發者模式  
> 右鍵頻道 → 複製頻道 ID

### 3. 安裝套件

```bash
pip install -r requirements.txt
```

### 4. 啟動 Bot

```bash
python bot.py
```

啟動後會看到：
```
 Bot 已登入：F1TaiwanBot#1234 (ID: ...)
 排程啟動，每 5 分鐘檢查一次
```

---

##  Embed 範例

### 賽前總通知（一般週末）

```
🏁 日本大獎賽來啦！
以下為台灣時間（GMT+8）

📅 3/7（五）
  FP1｜14:30
  FP2｜18:00

📅 3/8（六）
  FP3｜14:30
  Qualifying｜18:00

📅 3/9（日）
  Race｜15:00

────────────────────────────
F1 Taiwan Bot｜資料已轉換為台灣時間
```

### 賽前總通知（Sprint 週末，橘色）

```
🏁 邁阿密大獎賽來啦！⚡ Sprint 週末
以下為台灣時間（GMT+8）

📅 5/2（五）
  FP1｜00:30
  Sprint Qualifying｜04:30

📅 5/3（六）
  Sprint｜00:00
  Qualifying｜04:00

📅 5/4（日）
  Race｜04:00

⚡ 本站為 Sprint 週末，週六有 Sprint Qualifying + Sprint！
```

### 單場提醒

```
⏰ 比賽提醒
日本大獎賽 Qualifying 將在 1 小時後開始！

🕐 台灣時間   📍 地點
3/8（六）18:00  Japan
```

---

## ⚙️ 管理員指令

在 Discord 任意頻道輸入（需要管理員權限）：

| 指令 | 說明 |
|------|------|
| `!f1 status` | 查看 Bot 運作狀態與下一站資訊 |
| `!f1 next` | 立即預覽下一站賽程 Embed（不記錄） |
| `!f1 force` | 強制重新發送下一站賽前通知 |
| `!f1 log` | 查看最近 15 筆已發送記錄 |

---

##  進階設定

在 `config.py` 可調整：

```python
PRE_RACE_NOTIFY_DAYS = 3       # 賽前幾天發送通知（預設 3）
PRE_SESSION_NOTIFY_MINUTES = 60 # 場前幾分鐘發送提醒（預設 60）
CHECK_INTERVAL_MINUTES = 5      # 排程輪詢間隔（預設 5 分鐘）
```

---

##  資料來源

- **[OpenF1 API](https://openf1.org/)** — 免費、無需 API Key、即時更新
- 資料包含：年度賽程、各站 session 時間（UTC）、Sprint 週末判斷

---

##  未來擴充計畫

- [ ] `/race` `/points` 斜線指令（Slash Commands）
- [ ] 積分榜查詢
- [ ] 賽後完賽結果自動發布
- [ ] F1 新聞推送（LLM 中文口語翻譯）
- [ ] 資料異動自動偵測與更新

---

##  常見問題

**Bot 沒有發送訊息？**
1. 確認 `CHANNEL_ID` 是否正確
2. 確認 Bot 在該頻道有「傳送訊息」與「嵌入連結」權限
3. 確認該站賽前通知是否已發送（`!f1 log`）
4. 查看終端機 Log

**時間顯示錯誤？**
- OpenF1 API 資料以 UTC 提供，Bot 自動轉換為 GMT+8
- 若仍有問題請開 Issue 附上站名與 session 名稱

---

##  License

MIT License — 自由使用、修改與散布。

