# LINE 客服訊息紀錄系統

LINE 官方帳號 webhook → Cloudflare Worker → 規則/AI 回覆 → Turso (SQLite) → Streamlit 統計面板

## 架構

```
客人傳訊息 → LINE 平台 → Cloudflare Worker (worker/) → Turso 資料庫
                                                              ↓
                                          Streamlit (streamlit_app/) 讀取顯示/統計
```

## 1. 部署 Cloudflare Worker

```bash
cd worker
npm install

# 登入 Cloudflare
npx wrangler login

# 設定機密變數（會逐一提示輸入值，輸入後按 Enter）
npx wrangler secret put LINE_CHANNEL_SECRET
npx wrangler secret put LINE_CHANNEL_ACCESS_TOKEN
npx wrangler secret put TURSO_DATABASE_URL
npx wrangler secret put TURSO_AUTH_TOKEN
npx wrangler secret put OPENAI_API_KEY
npx wrangler secret put REMINDER_API_KEY

# 部署
npx wrangler deploy
```

部署完成後，會得到一個網址，例如：
```
https://line-lemon-webhook.你的帳號.workers.dev
```

## 2. 設定 LINE Webhook

到 [LINE Developers Console](https://developers.line.biz/) → 你的 Channel → Messaging API：

1. **Webhook URL** 填入上面 Worker 的網址
2. 點 **Verify** 測試連線是否成功
3. 開啟 **Use webhook**
4. 建議關閉「自動回應訊息」「加入好友歡迎訊息」中與 webhook 衝突的選項（依需求調整）

## 3. 部署 Streamlit

1. 到 [Streamlit Cloud](https://streamlit.io/cloud) 連結這個 GitHub repo
2. **Main file path** 填：`streamlit_app/app.py`
3. 到 App 的 **Settings → Secrets**，貼上（參考 `streamlit_app/secrets.toml.example`）：
   ```toml
   TURSO_DATABASE_URL = "libsql://你的資料庫網址.turso.io"
   TURSO_AUTH_TOKEN = "你的-auth-token"
   ```
4. Deploy

## 資料表結構（已在 Turso 建立）

```sql
CREATE TABLE line_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  line_user_id TEXT NOT NULL,
  display_name TEXT,
  message_text TEXT,
  message_type TEXT,
  received_at TEXT DEFAULT (datetime('now')),
  handled_by TEXT,
  status TEXT DEFAULT '未處理',
  note TEXT
);
```

## 週末服務 LINE 提醒

同一個 Worker 也負責週末服務提醒，不需要新增第二個 LINE Webhook：

- `orders-system` 呼叫 `/api/reminders/schedule` 建立排程。
- Cloudflare Cron 每分鐘檢查到期排程，可設定任意分鐘。
- 提醒訊息包含「已收到」Quick Reply（Postback）。
- 客人點擊後記錄訂單編號、服務日期、LINE user ID、發送及回覆時間。
- `orders-system` 透過 `/api/reminders/status` 同步並留存結果。

請為 `REMINDER_API_KEY` 產生高強度隨機值，並在 Cloudflare Worker Secret 與
`orders-system` Streamlit Secrets 使用相同內容，不可提交到 GitHub。

## 安全提醒

- `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`TURSO_AUTH_TOKEN`、`REMINDER_API_KEY` 絕對不要 commit 進 GitHub
- `.gitignore` 已排除 `.dev.vars`、`secrets.toml` 等機密檔案
- 若 Token 曾經貼在聊天視窗或公開過，建議到 Turso / LINE 後台重新產生一組新的

## AI 回覆安全分層

- 第一層：預約流程、服務範圍、會員查詢等，可依模板自動回覆。
- 第二層：報價、VIP、取消改期，只說明規則或蒐集資料，提示由專人確認。
- 第三層：客訴、退費、清潔不滿、賠償與金額爭議，停止 AI 代答並標記轉人工。
- 回覆順序為「資料庫自訂關鍵字 → 精簡規則上下文的 AI → 不回覆」，可降低 API token 與幻覺風險。
- 設定 `AI_AUTO_REPLY = "off"` 可隨時關閉 AI，保留既有關鍵字回覆。
