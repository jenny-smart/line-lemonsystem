# LINE Bot 訊息管理系統 Python 版

這是從 Google Apps Script 版整理出的 Python Web App。它把原本的 Apps Script + Google Sheet 後台改成：

- FastAPI 管理後台
- SQLite 資料庫
- LINE webhook 收訊
- 訊息管理、用戶管理、標籤管理
- 關鍵字自動回覆
- 群發訊息 API

## 本機啟動

```bash
cd python_app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export LINE_CHANNEL_SECRET="你的 LINE Channel Secret"
export LINE_CHANNEL_ACCESS_TOKEN="你的 LINE Channel Access Token"
uvicorn app:app --reload --port 8000
```

打開：

```text
http://127.0.0.1:8000/
```

LINE webhook URL 設定為：

```text
https://你的網域/webhook
```

## 環境變數

| 名稱 | 說明 |
| --- | --- |
| `LINE_CHANNEL_SECRET` | 驗證 LINE webhook 簽章 |
| `LINE_CHANNEL_ACCESS_TOKEN` | 取得 LINE profile、回覆、推播 |
| `DATABASE_PATH` | SQLite 檔案路徑，預設是 `python_app/linebot.sqlite3` |
| `PORT` | 用 `python app.py` 啟動時的 port，預設 `8000` |

## 和 GAS 版的差異

GAS 版用 Google Sheet 當資料庫；這版改用 SQLite，因此不需要 Google Sheet API key，也不需要 Apps Script 部署。

目前已轉出的主要功能：

- `doPost` webhook -> `POST /webhook`
- 訊息記錄 -> `messages` table
- 用戶記錄 -> `users` table
- 狀態更新 -> `PATCH /api/messages/{id}/status`
- 標籤管理 -> `/api/tags`
- 關鍵字回覆 -> `/api/keyword-replies`
- 群發訊息 -> `POST /api/broadcast`
