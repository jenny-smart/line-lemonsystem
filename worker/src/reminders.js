export const REMINDER_ACTION = "weekend_reminder_received";

export function makeReminderKey(orderNo, serviceDate) {
  return `${String(orderNo || "").trim()}|${String(serviceDate || "").trim()}`;
}

export function parseReminderPostback(data) {
  const params = new URLSearchParams(String(data || ""));
  if (params.get("action") !== REMINDER_ACTION) return null;
  const reminderKey = params.get("key") || "";
  return reminderKey ? { reminderKey } : null;
}

export function buildQuickReplyMessage(text, reminderKey) {
  const data = new URLSearchParams({
    action: REMINDER_ACTION,
    key: reminderKey,
  }).toString();
  return {
    type: "text",
    text,
    quickReply: {
      items: [{
        type: "action",
        action: {
          type: "postback",
          label: "已收到",
          data,
          displayText: "已收到",
        },
      }],
    },
  };
}

export async function ensureReminderSchema(db) {
  await db.execute(`
    CREATE TABLE IF NOT EXISTS weekend_reminders (
      reminder_key TEXT PRIMARY KEY,
      order_no TEXT NOT NULL,
      service_date TEXT NOT NULL,
      line_user_id TEXT NOT NULL,
      message_text TEXT NOT NULL,
      scheduled_at TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'scheduled',
      sent_at TEXT,
      replied_at TEXT,
      last_error TEXT,
      updated_at TEXT NOT NULL
    )
  `);
  await db.execute(`
    CREATE INDEX IF NOT EXISTS idx_weekend_reminders_due
    ON weekend_reminders(status, scheduled_at)
  `);
}

function normalizeReminder(raw) {
  const orderNo = String(raw?.order_no || "").trim();
  const serviceDate = String(raw?.service_date || "").trim();
  const lineUserId = String(raw?.line_user_id || "").trim();
  const messageText = String(raw?.message_text || "").trim();
  const scheduledDate = new Date(String(raw?.scheduled_at || ""));
  if (!orderNo || !serviceDate || !lineUserId.startsWith("U") || !messageText) {
    throw new Error("missing_or_invalid_reminder_fields");
  }
  if (Number.isNaN(scheduledDate.getTime())) {
    throw new Error("invalid_scheduled_at");
  }
  return {
    reminderKey: makeReminderKey(orderNo, serviceDate),
    orderNo,
    serviceDate,
    lineUserId,
    messageText,
    scheduledAt: scheduledDate.toISOString(),
  };
}

export async function scheduleReminders(db, reminders, now = new Date()) {
  await ensureReminderSchema(db);
  const saved = [];
  for (const raw of reminders || []) {
    const item = normalizeReminder(raw);
    await db.execute({
      sql: `INSERT INTO weekend_reminders
              (reminder_key, order_no, service_date, line_user_id, message_text,
               scheduled_at, status, sent_at, replied_at, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'scheduled', NULL, NULL, NULL, ?)
            ON CONFLICT(reminder_key) DO UPDATE SET
              line_user_id=excluded.line_user_id,
              message_text=excluded.message_text,
              scheduled_at=excluded.scheduled_at,
              status='scheduled',
              sent_at=NULL,
              replied_at=NULL,
              last_error=NULL,
              updated_at=excluded.updated_at`,
      args: [
        item.reminderKey, item.orderNo, item.serviceDate, item.lineUserId,
        item.messageText, item.scheduledAt, now.toISOString(),
      ],
    });
    saved.push({ reminder_key: item.reminderKey, scheduled_at: item.scheduledAt });
  }
  return saved;
}

export async function reminderStatuses(db, keys) {
  await ensureReminderSchema(db);
  const normalized = [...new Set((keys || []).map((key) => String(key || "").trim()).filter(Boolean))];
  if (!normalized.length) return [];
  const placeholders = normalized.map(() => "?").join(",");
  const result = await db.execute({
    sql: `SELECT reminder_key, order_no, service_date, line_user_id, scheduled_at,
                 status, sent_at, replied_at, last_error
          FROM weekend_reminders
          WHERE reminder_key IN (${placeholders})`,
    args: normalized,
  });
  return (result.rows || []).map((row) => ({ ...row }));
}

async function pushReminder(lineUserId, message, accessToken, fetchImpl) {
  return fetchImpl("https://api.line.me/v2/bot/message/push", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ to: lineUserId, messages: [message] }),
  });
}

export async function processDueReminders(
  db,
  accessToken,
  { now = new Date(), fetchImpl = fetch, limit = 100 } = {},
) {
  await ensureReminderSchema(db);
  const scheduled = await db.execute({
    sql: `SELECT reminder_key, line_user_id, message_text, scheduled_at
          FROM weekend_reminders
          WHERE status='scheduled'
          ORDER BY scheduled_at ASC LIMIT ?`,
    args: [limit],
  });
  // Turso/SQLite deployments can compare ISO timestamp parameters differently
  // depending on the stored value's offset format. Parse both sides in
  // JavaScript so an already-due reminder is never skipped by text comparison.
  const nowMs = now.getTime();
  const dueRows = (scheduled.rows || []).filter((row) => {
    const scheduledMs = new Date(String(row.scheduled_at || "")).getTime();
    return Number.isFinite(scheduledMs) && scheduledMs <= nowMs;
  });
  let sent = 0;
  let failed = 0;
  const errors = [];
  for (const row of dueRows) {
    const response = await pushReminder(
      row.line_user_id,
      buildQuickReplyMessage(row.message_text, row.reminder_key),
      accessToken,
      fetchImpl,
    );
    if (response.ok) {
      sent += 1;
      await db.execute({
        sql: `UPDATE weekend_reminders
              SET status='sent', sent_at=?, last_error=NULL, updated_at=?
              WHERE reminder_key=? AND status='scheduled'`,
        args: [now.toISOString(), now.toISOString(), row.reminder_key],
      });
    } else {
      failed += 1;
      const errorText = `${response.status} ${(await response.text()).slice(0, 500)}`.trim();
      errors.push({ reminderKey: row.reminder_key, detail: errorText });
      await db.execute({
        sql: `UPDATE weekend_reminders
              SET status='failed', last_error=?, updated_at=?
              WHERE reminder_key=? AND status='scheduled'`,
        args: [errorText, now.toISOString(), row.reminder_key],
      });
    }
  }
  return {
    found: dueRows.length,
    sent,
    failed,
    scanned: (scheduled.rows || []).length,
    now: Number.isFinite(nowMs) ? new Date(nowMs).toISOString() : String(now),
    nextScheduledAt: scheduled.rows?.[0]?.scheduled_at || null,
    errors,
  };
}

export async function recordReminderReply(db, reminderKey, lineUserId, now = new Date()) {
  await ensureReminderSchema(db);
  const result = await db.execute({
    sql: `UPDATE weekend_reminders
          SET status='replied', line_user_id=?, replied_at=?, updated_at=?
          WHERE reminder_key=?`,
    args: [lineUserId, now.toISOString(), now.toISOString(), reminderKey],
  });
  return Number(result.rowsAffected || 0) > 0;
}
