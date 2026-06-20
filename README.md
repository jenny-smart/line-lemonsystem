# LINE 客服訊息紀錄系統

LINE 官方帳號 webhook → Cloudflare Worker → Turso (SQLite) → Streamlit 統計面板

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

## 安全提醒

- `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`TURSO_AUTH_TOKEN` 絕對不要 commit 進 GitHub
- `.gitignore` 已排除 `.dev.vars`、`secrets.toml` 等機密檔案
- 若 Token 曾經貼在聊天視窗或公開過，建議到 Turso / LINE 後台重新產生一組新的
