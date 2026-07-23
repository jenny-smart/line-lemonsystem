import test from "node:test";
import assert from "node:assert/strict";

import {
  REMINDER_ACTION,
  buildQuickReplyMessage,
  makeReminderKey,
  parseReminderPostback,
  processDueReminders,
  recordReminderReply,
  scheduleReminders,
} from "../src/reminders.js";

test("builds a stable reminder key", () => {
  assert.equal(makeReminderKey("LC001", "2026-07-25"), "LC001|2026-07-25");
});

test("builds LINE quick reply postback payload", () => {
  const message = buildQuickReplyMessage("提醒內容", "LC001|2026-07-25");
  const action = message.quickReply.items[0].action;
  assert.equal(message.type, "text");
  assert.equal(action.type, "postback");
  assert.equal(action.label, "已收到");
  const params = new URLSearchParams(action.data);
  assert.equal(params.get("action"), REMINDER_ACTION);
  assert.equal(params.get("key"), "LC001|2026-07-25");
});

test("parses only reminder postbacks", () => {
  assert.deepEqual(
    parseReminderPostback("action=weekend_reminder_received&key=LC001%7C2026-07-25"),
    { reminderKey: "LC001|2026-07-25" },
  );
  assert.equal(parseReminderPostback("action=other&key=LC001"), null);
});

test("does not reset reminders that were already sent", async () => {
  let upsertSql = "";
  const db = {
    async execute(query) {
      if (typeof query === "string") return { rows: [] };
      upsertSql = query.sql;
      return { rowsAffected: 0, rows: [] };
    },
  };
  await scheduleReminders(db, [{
    order_no: "LC001",
    service_date: "2026-07-25",
    line_user_id: "U-user",
    message_text: "提醒",
    scheduled_at: "2026-07-24T01:00:00.000Z",
  }]);
  assert.match(
    upsertSql,
    /WHERE weekend_reminders\.status IN \('scheduled', 'failed'\)/,
  );
});

test("sends due reminder and records postback reply", async () => {
  const updates = [];
  const db = {
    async execute(query) {
      if (typeof query === "string") return { rows: [] };
      if (query.sql.includes("SELECT reminder_key")) {
        return {
          rows: [{
            reminder_key: "LC001|2026-07-25",
            line_user_id: "U-user",
            message_text: "提醒",
            scheduled_at: "2026-07-24T01:02:00.000Z",
          }, {
            reminder_key: "LC002|2026-07-25",
            line_user_id: "U-future",
            message_text: "未到時間",
            scheduled_at: "2026-07-24T01:05:00.000Z",
          }],
        };
      }
      if (query.sql.includes("UPDATE weekend_reminders")) {
        updates.push(query);
        return { rowsAffected: 1, rows: [] };
      }
      return { rows: [] };
    },
  };
  let pushed;
  const fetchImpl = async (_url, options) => {
    pushed = JSON.parse(options.body);
    return { ok: true, status: 200, text: async () => "" };
  };
  const result = await processDueReminders(db, "token", {
    now: new Date("2026-07-24T01:03:00.000Z"),
    fetchImpl,
  });
  assert.deepEqual(result, {
    found: 1,
    sent: 1,
    failed: 0,
    scanned: 2,
    now: "2026-07-24T01:03:00.000Z",
    nextScheduledAt: "2026-07-24T01:02:00.000Z",
    errors: [],
  });
  assert.equal(pushed.to, "U-user");
  assert.equal(pushed.messages[0].quickReply.items[0].action.label, "已收到");

  const recorded = await recordReminderReply(
    db,
    "LC001|2026-07-25",
    "U-user",
    new Date("2026-07-24T01:04:00.000Z"),
  );
  assert.equal(recorded, true);
  assert.equal(updates.length, 2);
});
