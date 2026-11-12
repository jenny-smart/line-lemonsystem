import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

import {
  confirmSignature,
  confirmationStatuses,
  handleConfirm,
  isExpired,
  parseConfirmPath,
  serviceDateLabel,
} from "../src/confirm.js";

const SECRET = "test-secret";
const env = { REMINDER_API_KEY: SECRET };

function fakeDb() {
  const rows = new Map();
  return {
    rows,
    async execute(query) {
      const sql = typeof query === "string" ? query : query.sql;
      const args = typeof query === "string" ? [] : query.args;
      if (sql.includes("INSERT INTO reminder_confirmations")) {
        if (!rows.has(args[0])) rows.set(args[0], { reminder_key: args[0], order_no: args[1], service_date: args[2], confirmed_at: args[3] });
        return { rows: [] };
      }
      if (sql.includes("SELECT confirmed_at")) {
        return { rows: rows.has(args[0]) ? [rows.get(args[0])] : [] };
      }
      if (sql.includes("SELECT reminder_key")) {
        return { rows: args.filter((k) => rows.has(k)).map((k) => rows.get(k)) };
      }
      return { rows: [] };
    },
  };
}

async function link(orderNo = "LC002200072", date = "2026-11-15") {
  const sig = await confirmSignature(SECRET, orderNo, date);
  return `/c/${orderNo}/${date.replaceAll("-", "")}/${sig}`;
}

const NOW = new Date("2026-11-13T02:00:00Z");

test("signature matches the Python side (HMAC-SHA256 hex, first 16 chars)", async () => {
  const expected = createHmac("sha256", SECRET).update("confirm|LC002200072|2026-11-15").digest("hex").slice(0, 16);
  assert.equal(await confirmSignature(SECRET, "LC002200072", "2026-11-15"), expected);
});

test("parses only well-formed confirm paths", () => {
  assert.deepEqual(parseConfirmPath("/c/LC002200072/20261115/0123456789abcdef"), {
    orderNo: "LC002200072", serviceDate: "2026-11-15", signature: "0123456789abcdef",
  });
  assert.equal(parseConfirmPath("/c/LC002200072/20261115"), null);
  assert.equal(parseConfirmPath("/c/<script>/20261115/0123456789abcdef"), null);
  assert.equal(parseConfirmPath("/c/LC002200072/2026-11-15/0123456789abcdef"), null);
  assert.equal(parseConfirmPath("/x/LC002200072/20261115/0123456789abcdef"), null);
});

test("date label and expiry use Taipei time", () => {
  assert.equal(serviceDateLabel("2026-11-15"), "11/15（日）");
  assert.equal(isExpired("2026-11-15", new Date("2026-11-17T15:59:00Z")), false);
  assert.equal(isExpired("2026-11-15", new Date("2026-11-17T16:00:00Z")), true);
});

test("GET shows the page but never records (LINE link preview safe)", async () => {
  const db = fakeDb();
  const res = await handleConfirm(new Request(`https://w.dev${await link()}`), env, await link(), () => db, NOW);
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.match(html, /確認收到/);
  assert.match(html, /11\/15（日）/);
  assert.equal(db.rows.size, 0);
});

test("POST records once and keeps the first confirmation time", async () => {
  const db = fakeDb();
  const path = await link();
  const post = () => new Request(`https://w.dev${path}`, { method: "POST" });
  const first = await handleConfirm(post(), env, path, () => db, NOW);
  assert.equal(first.status, 200);
  assert.match(await first.text(), /已確認收到/);
  await handleConfirm(post(), env, path, () => db, new Date("2026-11-13T05:00:00Z"));
  const statuses = await confirmationStatuses(db, ["LC002200072|2026-11-15", "LC1|2026-11-15"]);
  assert.deepEqual(statuses, [{
    reminder_key: "LC002200072|2026-11-15", order_no: "LC002200072",
    service_date: "2026-11-15", confirmed_at: NOW.toISOString(),
  }]);
});

test("wrong signature, expired link and missing secret are rejected without recording", async () => {
  const db = fakeDb();
  const bad = "/c/LC002200072/20261115/0000000000000000";
  const post = (path) => new Request(`https://w.dev${path}`, { method: "POST" });
  assert.equal((await handleConfirm(post(bad), env, bad, () => db, NOW)).status, 404);
  const other = (await link()).replace("20261115", "20261114");
  assert.equal((await handleConfirm(post(other), env, other, () => db, NOW)).status, 404);
  const path = await link();
  assert.equal((await handleConfirm(post(path), env, path, () => db, new Date("2026-11-20T00:00:00Z"))).status, 410);
  assert.equal((await handleConfirm(post(path), {}, path, () => db, NOW)).status, 503);
  assert.equal(db.rows.size, 0);
});
