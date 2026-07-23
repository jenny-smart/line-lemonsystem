import { createClient } from "@libsql/client/web";
import { classifyRisk, generateAiReply, HUMAN_HANDOFF_REPLY } from "./ai.js";
import {
  parseReminderPostback,
  processDueReminders,
  recordReminderReply,
  reminderStatuses,
  scheduleReminders,
} from "./reminders.js";

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

async function recentConversation(db, userId) {
  const rs = await db.execute({
    sql: `SELECT message_text FROM line_messages
          WHERE line_user_id=? ORDER BY id DESC LIMIT 4`,
    args: [userId],
  });
  return (rs.rows || []).map((row) => row.message_text || row[0]).filter(Boolean).reverse();
}

async function markForHuman(db, userId, reason) {
  await db.execute({
    sql: `UPDATE line_messages
          SET status='未處理', note=?
          WHERE id=(SELECT MAX(id) FROM line_messages WHERE line_user_id=?)`,
    args: [`AI轉人工：${reason}`, userId],
  });
}

function connectDb(env) {
  return createClient({
    url: env.TURSO_DATABASE_URL,
    authToken: env.TURSO_AUTH_TOKEN,
  });
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function authorized(request, env) {
  return Boolean(env.REMINDER_API_KEY) &&
    request.headers.get("authorization") === `Bearer ${env.REMINDER_API_KEY}`;
}

async function reminderApi(request, env, pathname) {
  if (!env.REMINDER_API_KEY) {
    return jsonResponse({ error: "REMINDER_API_KEY is not configured" }, 503);
  }
  if (!authorized(request, env)) {
    return jsonResponse({ error: "unauthorized" }, 401);
  }
  const db = connectDb(env);
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }
  try {
    if (request.method === "POST" && pathname === "/api/reminders/schedule") {
      const saved = await scheduleReminders(db, body.reminders);
      return jsonResponse({ ok: true, reminders: saved });
    }
    if (request.method === "POST" && pathname === "/api/reminders/status") {
      const reminders = await reminderStatuses(db, body.keys);
      return jsonResponse({ ok: true, reminders });
    }
  } catch (error) {
    return jsonResponse({ error: String(error?.message || error) }, 400);
  }
  return jsonResponse({ error: "not_found" }, 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/reminders/")) {
      return reminderApi(request, env, url.pathname);
    }
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
    const db = connectDb(env);

    for (const event of events) {
      const userId = event.source?.userId;
      if (event.type === "postback") {
        const reminder = parseReminderPostback(event.postback?.data);
        if (reminder && userId) {
          const recorded = await recordReminderReply(db, reminder.reminderKey, userId);
          if (recorded) {
            await replyMessage(event.replyToken, "已記錄您收到服務提醒，謝謝您。", env.LINE_CHANNEL_ACCESS_TOKEN);
          }
        }
        continue;
      }

      // 一般客服訊息維持原有紀錄與自動回覆流程。
      if (event.type !== "message") continue;

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

      if (messageType === "text") {
        const risk = classifyRisk(messageText);
        if (risk.needsHuman) {
          await markForHuman(db, userId, risk.reason);
          await replyMessage(event.replyToken, HUMAN_HANDOFF_REPLY, env.LINE_CHANNEL_ACCESS_TOKEN);
          continue;
        }

        // 資料庫自訂關鍵字優先，AI 僅補足自然語意，避免不必要的 API 花費。
        let autoReply = await findKeywordReply(db, messageText);
        if (!autoReply && env.AI_AUTO_REPLY !== "off") {
          autoReply = await generateAiReply({
            env,
            messageText,
            displayName,
            recentMessages: await recentConversation(db, userId),
          });
        }
        if (autoReply) {
          await replyMessage(event.replyToken, autoReply, env.LINE_CHANNEL_ACCESS_TOKEN);
        }
      }
    }

    return new Response("OK", { status: 200 });
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil((async () => {
      const result = await processDueReminders(
        connectDb(env),
        env.LINE_CHANNEL_ACCESS_TOKEN,
        { now: new Date(controller.scheduledTime) },
      );
      console.log("Reminder cron result", JSON.stringify(result));
    })());
  },
};
