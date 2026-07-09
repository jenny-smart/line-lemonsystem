import base64
import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "linebot.sqlite3"))
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

STATUS_OPTIONS = [
    {"id": "unreplied", "name": "未回覆", "color": "#ffc107"},
    {"id": "replied", "name": "已回覆", "color": "#17a2b8"},
    {"id": "processing", "name": "處理中", "color": "#fd7e14"},
    {"id": "waiting_user", "name": "待用戶回覆", "color": "#6f42c1"},
    {"id": "resolved", "name": "已解決", "color": "#28a745"},
    {"id": "closed", "name": "已關閉", "color": "#6c757d"},
]

app = FastAPI(title="LINE Bot 訊息管理系統")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              line_event_id TEXT UNIQUE,
              line_user_id TEXT NOT NULL,
              display_name TEXT,
              content TEXT,
              event_type TEXT,
              message_type TEXT,
              status TEXT DEFAULT 'unreplied',
              read_status TEXT DEFAULT 'unread',
              replied_by TEXT,
              note TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
              line_user_id TEXT PRIMARY KEY,
              display_name TEXT,
              edited_name TEXT,
              picture_url TEXT,
              tags TEXT DEFAULT '',
              first_interaction TEXT,
              last_interaction TEXT,
              interaction_count INTEGER DEFAULT 0,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE NOT NULL,
              color TEXT DEFAULT '#06C755',
              description TEXT DEFAULT '',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS keyword_replies (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              keyword TEXT NOT NULL,
              reply_text TEXT NOT NULL,
              enabled INTEGER DEFAULT 1,
              match_type TEXT DEFAULT 'contains',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS broadcast_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              message TEXT NOT NULL,
              success_count INTEGER DEFAULT 0,
              fail_count INTEGER DEFAULT 0,
              total_count INTEGER DEFAULT 0,
              created_at TEXT NOT NULL
            );
            """
        )


def verify_signature(body: bytes, signature: str | None) -> bool:
    if not LINE_CHANNEL_SECRET or not signature:
        return True
    digest = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def get_line_profile(user_id: str) -> dict[str, Any]:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return {}
    try:
        response = requests.get(
            f"https://api.line.me/v2/bot/profile/{user_id}",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=8,
        )
        if response.ok:
            return response.json()
    except requests.RequestException:
        pass
    return {}


def send_reply(reply_token: str, text: str) -> bool:
    if not LINE_CHANNEL_ACCESS_TOKEN or not reply_token:
        return False
    response = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
        timeout=8,
    )
    return response.ok


def send_push(user_id: str, text: str) -> bool:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    response = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"to": user_id, "messages": [{"type": "text", "text": text}]},
        timeout=8,
    )
    return response.ok


def message_text(event: dict[str, Any]) -> tuple[str, str]:
    message = event.get("message") or {}
    message_type = message.get("type", "unknown")
    if message_type == "text":
        return message.get("text", ""), message_type
    return f"[{message_type} 訊息]", message_type


def upsert_user(conn: sqlite3.Connection, user_id: str, display_name: str, profile: dict[str, Any]) -> None:
    timestamp = now_iso()
    existing = conn.execute("SELECT line_user_id, interaction_count, first_interaction FROM users WHERE line_user_id = ?", [user_id]).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE users
            SET display_name = ?, picture_url = COALESCE(?, picture_url),
                last_interaction = ?, interaction_count = interaction_count + 1, updated_at = ?
            WHERE line_user_id = ?
            """,
            [display_name, profile.get("pictureUrl"), timestamp, timestamp, user_id],
        )
    else:
        conn.execute(
            """
            INSERT INTO users
              (line_user_id, display_name, picture_url, first_interaction, last_interaction, interaction_count, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            [user_id, display_name, profile.get("pictureUrl"), timestamp, timestamp, timestamp],
        )


def log_message(event: dict[str, Any]) -> None:
    source = event.get("source") or {}
    user_id = source.get("userId")
    if not user_id:
        return

    content, msg_type = message_text(event)
    profile = get_line_profile(user_id)
    display_name = profile.get("displayName") or user_id
    event_id = f"{event.get('replyToken', '')}_{event.get('timestamp', '')}"

    with db() as conn:
        upsert_user(conn, user_id, display_name, profile)
        conn.execute(
            """
            INSERT OR IGNORE INTO messages
              (line_event_id, line_user_id, display_name, content, event_type, message_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [event_id, user_id, display_name, content, event.get("type", ""), msg_type, now_iso()],
        )


def keyword_reply_for(content: str) -> str | None:
    with db() as conn:
        rows = conn.execute("SELECT * FROM keyword_replies WHERE enabled = 1 ORDER BY id").fetchall()
    for row in rows:
        keyword = row["keyword"]
        if row["match_type"] == "exact" and content == keyword:
            return row["reply_text"]
        if row["match_type"] != "exact" and keyword in content:
            return row["reply_text"]
    return None


def handle_event(event: dict[str, Any]) -> None:
    if event.get("type") == "message":
        log_message(event)
        content, msg_type = message_text(event)
        if msg_type == "text":
            reply = keyword_reply_for(content)
            if reply:
                send_reply(event.get("replyToken", ""), reply)
    elif event.get("type") == "follow":
        source = event.get("source") or {}
        user_id = source.get("userId")
        if user_id:
            profile = get_line_profile(user_id)
            with db() as conn:
                upsert_user(conn, user_id, profile.get("displayName") or user_id, profile)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request, "status_options": STATUS_OPTIONS})


@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str | None = Header(default=None)) -> JSONResponse:
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        raise HTTPException(status_code=401, detail="Invalid LINE signature")
    payload = json.loads(body.decode() or "{}")
    for event in payload.get("events", []):
        handle_event(event)
    return JSONResponse({"status": "success"})


@app.get("/api/status-options")
def status_options() -> list[dict[str, str]]:
    return STATUS_OPTIONS


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    today = datetime.now().date().isoformat()
    with db() as conn:
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        active_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        today_messages = conn.execute("SELECT COUNT(*) FROM messages WHERE substr(created_at, 1, 10) = ?", [today]).fetchone()[0]
        replied = conn.execute("SELECT COUNT(*) FROM messages WHERE status IN ('replied', 'resolved', 'closed')").fetchone()[0]
    return {
        "totalMessages": total_messages,
        "activeUsers": active_users,
        "todayMessages": today_messages,
        "responseRate": round((replied / total_messages) * 100) if total_messages else 0,
    }


@app.get("/api/messages")
def list_messages(
    status: str = "",
    keyword: str = "",
    user_id: str = "",
    tag: str = "",
    start_date: str = "",
    end_date: str = "",
    page: int = 1,
    page_size: int = 30,
) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("m.status = ?")
        params.append(status)
    if keyword:
        clauses.append("(m.content LIKE ? OR m.display_name LIKE ? OR u.edited_name LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    if user_id:
        clauses.append("m.line_user_id LIKE ?")
        params.append(f"%{user_id}%")
    if tag:
        clauses.append("u.tags LIKE ?")
        params.append(f"%{tag}%")
    if start_date:
        clauses.append("date(m.created_at) >= date(?)")
        params.append(start_date)
    if end_date:
        clauses.append("date(m.created_at) <= date(?)")
        params.append(end_date)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    offset = max(page - 1, 0) * page_size
    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM messages m LEFT JOIN users u ON u.line_user_id = m.line_user_id {where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT m.*, u.edited_name, u.tags
            FROM messages m
            LEFT JOIN users u ON u.line_user_id = m.line_user_id
            {where}
            ORDER BY m.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()
    return {
        "items": rows_to_dicts(rows),
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size,
    }


@app.patch("/api/messages/{message_id}/status")
async def update_message_status(message_id: int, request: Request) -> dict[str, Any]:
    payload = await request.json()
    status = payload.get("status")
    if status not in {item["id"] for item in STATUS_OPTIONS}:
        raise HTTPException(status_code=400, detail="Unknown status")
    with db() as conn:
        conn.execute("UPDATE messages SET status = ? WHERE id = ?", [status, message_id])
    return {"success": True}


@app.get("/api/users")
def list_users(keyword: str = "", tag: str = "", page: int = 1, page_size: int = 30) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []
    if keyword:
        clauses.append("(display_name LIKE ? OR edited_name LIKE ? OR line_user_id LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    if tag:
        clauses.append("tags LIKE ?")
        params.append(f"%{tag}%")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    offset = max(page - 1, 0) * page_size
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM users {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM users {where} ORDER BY last_interaction DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
    return {"items": rows_to_dicts(rows), "total": total, "page": page, "pageSize": page_size}


@app.patch("/api/users/{user_id}")
async def update_user(user_id: str, request: Request) -> dict[str, Any]:
    payload = await request.json()
    tags = payload.get("tags", "")
    if isinstance(tags, list):
        tags = ", ".join(tags)
    with db() as conn:
        conn.execute(
            "UPDATE users SET edited_name = ?, tags = ?, updated_at = ? WHERE line_user_id = ?",
            [payload.get("editedName", ""), tags, now_iso(), user_id],
        )
    return {"success": True}


@app.get("/api/tags")
def list_tags() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
    return rows_to_dicts(rows)


@app.post("/api/tags")
async def save_tag(request: Request) -> dict[str, Any]:
    payload = await request.json()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO tags(name, color, description, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET color = excluded.color, description = excluded.description
            """,
            [payload["name"], payload.get("color", "#06C755"), payload.get("description", ""), now_iso()],
        )
    return {"success": True}


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int) -> dict[str, Any]:
    with db() as conn:
        conn.execute("DELETE FROM tags WHERE id = ?", [tag_id])
    return {"success": True}


@app.get("/api/keyword-replies")
def list_keyword_replies() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM keyword_replies ORDER BY id DESC").fetchall()
    return rows_to_dicts(rows)


@app.post("/api/keyword-replies")
async def save_keyword_reply(request: Request) -> dict[str, Any]:
    payload = await request.json()
    timestamp = now_iso()
    with db() as conn:
        if payload.get("id"):
            conn.execute(
                """
                UPDATE keyword_replies
                SET keyword = ?, reply_text = ?, enabled = ?, match_type = ?, updated_at = ?
                WHERE id = ?
                """,
                [
                    payload["keyword"],
                    payload["replyText"],
                    int(payload.get("enabled", True)),
                    payload.get("matchType", "contains"),
                    timestamp,
                    payload["id"],
                ],
            )
        else:
            conn.execute(
                """
                INSERT INTO keyword_replies(keyword, reply_text, enabled, match_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    payload["keyword"],
                    payload["replyText"],
                    int(payload.get("enabled", True)),
                    payload.get("matchType", "contains"),
                    timestamp,
                    timestamp,
                ],
            )
    return {"success": True}


@app.delete("/api/keyword-replies/{reply_id}")
def delete_keyword_reply(reply_id: int) -> dict[str, Any]:
    with db() as conn:
        conn.execute("DELETE FROM keyword_replies WHERE id = ?", [reply_id])
    return {"success": True}


@app.post("/api/broadcast")
async def broadcast(request: Request) -> dict[str, Any]:
    payload = await request.json()
    message = payload.get("message", "").strip()
    user_ids = payload.get("userIds") or []
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    if not user_ids:
        with db() as conn:
            user_ids = [row["line_user_id"] for row in conn.execute("SELECT line_user_id FROM users").fetchall()]
    success_count = 0
    fail_count = 0
    for user_id in user_ids:
        if send_push(user_id, message):
            success_count += 1
        else:
            fail_count += 1
    with db() as conn:
        conn.execute(
            "INSERT INTO broadcast_logs(message, success_count, fail_count, total_count, created_at) VALUES (?, ?, ?, ?, ?)",
            [message, success_count, fail_count, len(user_ids), now_iso()],
        )
    return {"success": True, "successCount": success_count, "failCount": fail_count, "totalCount": len(user_ids)}


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
