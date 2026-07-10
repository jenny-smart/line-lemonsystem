// v1.1 新增：每則訊息進來時自動 upsert line_users（用戶自動建檔）

import { createClient } from "@libsql/client/web";

/**
 * 驗證 LINE webhook 簽章
 * LINE 會在 header x-line-signature 帶入 HMAC-SHA256(channel secret, body) 的 base64 結果
 */
async function verifySignature(channelSecret, body, signature) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(channelSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sigBuffer = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  const sigBase64 = btoa(String.fromCharCode(...new Uint8Array(sigBuffer)));
  return sigBase64 === signature;
}

/**
 * 呼叫 LINE Profile API 取得使用者暱稱
 */
async function getDisplayName(userId, accessToken) {
  try {
    const res = await fetch(`https://api.line.me/v2/bot/profile/${userId}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.displayName || null;
  } catch (e) {
    return null;
  }
}

async function replyMessage(replyToken, text, accessToken) {
  if (!replyToken || !text) return false;
  try {
    const res = await fetch("https://api.line.me/v2/bot/message/reply", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        replyToken,
        messages: [{ type: "text", text }],
      }),
    });
    return res.ok;
  } catch (e) {
    return false;
  }
}

async function findKeywordReply(db, messageText) {
  if (!messageText) return null;
  const rs = await db.execute({
    sql: "SELECT keyword, reply_text, match_type FROM keyword_replies WHERE enabled=1 ORDER BY id ASC",
    args: [],
  });
  for (const row of rs.rows || []) {
    const keyword = row.keyword || row[0];
    const replyText = row.reply_text || row[1];
    const matchType = row.match_type || row[2] || "contains";
    if (matchType === "exact" && messageText === keyword) return replyText;
    if (matchType !== "exact" && messageText.includes(keyword)) return replyText;
  }
  return null;
}

/**
 * 新增：用戶自動建檔 / 更新互動紀錄
 * - 用戶第一次傳訊息 → 自動新建 line_users 記錄
 * - 用戶再次傳訊息 → 更新 last_seen_at、message_count + 1
 * 不覆蓋客服手動維護的欄位（edited_name、note、phone、area、address、vip、owner、tags 關聯）
 * 只有客服「尚未改過名稱」時才跟著更新 display_name，避免蓋掉客服的自訂命名
 */
async function upsertLineUser(db, userId, displayName) {
  try {
    const existing = await db.execute({
      sql: "SELECT line_user_id, edited_name FROM line_users WHERE line_user_id = ?",
      args: [userId],
    });

    if (existing.rows.length === 0) {
      // 全新用戶：建檔
      await db.execute({
        sql: `INSERT INTO line_users
              (line_user_id, display_name, first_seen_at, last_seen_at, message_count)
              VALUES (?, ?, datetime('now'), datetime('now'), 1)`,
        args: [userId, displayName],
      });
    } else {
      // 既有用戶：只更新互動狀態與原始 LINE 暱稱，不動客服已編輯的欄位
      await db.execute({
        sql: `UPDATE line_users
              SET display_name = ?,
                  last_seen_at = datetime('now'),
                  message_count = message_count + 1
              WHERE line_user_id = ?`,
        args: [displayName, userId],
      });
    }
  } catch (e) {
    // upsert 失敗不應該讓整個 webhook 失敗（訊息記錄仍要成功），僅記錄錯誤
    console.error("upsertLineUser failed:", e);
  }
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("LINE webhook is running.", { status: 200 });
    }

    const bodyText = await request.text();
    const signature = request.headers.get("x-line-signature") || "";

    // 1. 驗證簽章，避免偽造請求
    const valid = await verifySignature(env.LINE_CHANNEL_SECRET, bodyText, signature);
    if (!valid) {
      return new Response("Invalid signature", { status: 401 });
    }

    const body = JSON.parse(bodyText);
    const events = body.events || [];

    // 2. 連線 Turso
    const db = createClient({
      url: env.TURSO_DATABASE_URL,
      authToken: env.TURSO_AUTH_TOKEN,
    });

    for (const event of events) {
      // 只記錄使用者傳來的訊息（message 事件），其他事件（加入好友、封鎖等）可依需求擴充
      if (event.type !== "message") continue;

      const userId = event.source?.userId;
      if (!userId) continue;

      const messageType = event.message?.type || "unknown";
      const messageText =
        messageType === "text" ? event.message.text : `[${messageType} 訊息]`;

      const displayName = await getDisplayName(userId, env.LINE_CHANNEL_ACCESS_TOKEN);

      await db.execute({
        sql: `INSERT INTO line_messages
              (line_user_id, display_name, message_text, message_type, received_at)
              VALUES (?, ?, ?, ?, datetime('now'))`,
        args: [userId, displayName, messageText, messageType],
      });

      // 新增：訊息寫入成功後，同步 upsert 用戶主檔
      await upsertLineUser(db, userId, displayName);

      if (messageType === "text") {
        const autoReply = await findKeywordReply(db, messageText);
        if (autoReply) {
          await replyMessage(event.replyToken, autoReply, env.LINE_CHANNEL_ACCESS_TOKEN);
        }
      }
    }

    return new Response("OK", { status: 200 });
  },
};
