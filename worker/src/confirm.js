/**
 * 週末提醒「確認收到」連結。
 *
 * order-system 在提醒訊息裡附上 /c/{訂單編號}/{YYYYMMDD}/{簽章}，客服照常在 chat.line.biz 發送。
 * 客人點開是一個確認頁，要再按「確認收到」（POST）才記錄：LINE 會自動預覽訊息裡的網址，
 * 所以 GET 絕對不能寫入。簽章＝HMAC-SHA256(REMINDER_API_KEY, "confirm|訂單編號|YYYY-MM-DD") 前 16 碼，
 * 不需要事先登記，也不需要知道客人的 LINE user ID。
 */
export const CONFIRM_PATH_PREFIX = "/c/";
const ORDER_NO_RE = /^[A-Z]{2}\d{6,12}$/;
const EXPIRE_DAYS_AFTER_SERVICE = 2;
const WEEKDAYS = "日一二三四五六";

export function confirmationKey(orderNo, serviceDate) {
  return `${orderNo}|${serviceDate}`;
}

export async function confirmSignature(secret, orderNo, serviceDate) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", encoder.encode(String(secret)), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const data = encoder.encode(`confirm|${orderNo}|${serviceDate}`);
  const bytes = new Uint8Array(await crypto.subtle.sign("HMAC", key, data));
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

/** /c/LC00220007/20261115/abcdef0123456789 → { orderNo, serviceDate: "2026-11-15", signature }；格式不對回 null。 */
export function parseConfirmPath(pathname) {
  const parts = String(pathname || "").slice(CONFIRM_PATH_PREFIX.length).split("/");
  if (!String(pathname || "").startsWith(CONFIRM_PATH_PREFIX) || parts.length !== 3) return null;
  const [orderNo, compactDate, signature] = parts;
  if (!ORDER_NO_RE.test(orderNo) || !/^\d{8}$/.test(compactDate) || !/^[0-9a-f]{16}$/.test(signature)) return null;
  const serviceDate = `${compactDate.slice(0, 4)}-${compactDate.slice(4, 6)}-${compactDate.slice(6, 8)}`;
  if (Number.isNaN(Date.parse(`${serviceDate}T00:00:00+08:00`))) return null;
  return { orderNo, serviceDate, signature };
}

function sameText(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export function isExpired(serviceDate, now = new Date()) {
  const end = Date.parse(`${serviceDate}T00:00:00+08:00`) + (EXPIRE_DAYS_AFTER_SERVICE + 1) * 86400000;
  return now.getTime() >= end;
}

export function serviceDateLabel(serviceDate) {
  const [, month, day] = serviceDate.split("-").map(Number);
  const weekday = new Date(`${serviceDate}T12:00:00+08:00`).getUTCDay();
  return `${month}/${day}（${WEEKDAYS[weekday]}）`;
}

export async function ensureConfirmSchema(db) {
  await db.execute(`
    CREATE TABLE IF NOT EXISTS reminder_confirmations (
      reminder_key TEXT PRIMARY KEY,
      order_no TEXT NOT NULL,
      service_date TEXT NOT NULL,
      confirmed_at TEXT NOT NULL
    )
  `);
}

async function confirmedAt(db, key) {
  const rs = await db.execute({
    sql: "SELECT confirmed_at FROM reminder_confirmations WHERE reminder_key=?",
    args: [key],
  });
  const row = (rs.rows || [])[0];
  return row ? (row.confirmed_at || row[0]) : "";
}

/** 記錄確認（保留第一次確認的時間）；回傳確認時間 ISO 字串。 */
export async function recordConfirmation(db, orderNo, serviceDate, now = new Date()) {
  await ensureConfirmSchema(db);
  const key = confirmationKey(orderNo, serviceDate);
  await db.execute({
    sql: `INSERT INTO reminder_confirmations (reminder_key, order_no, service_date, confirmed_at)
          VALUES (?, ?, ?, ?) ON CONFLICT(reminder_key) DO NOTHING`,
    args: [key, orderNo, serviceDate, now.toISOString()],
  });
  return (await confirmedAt(db, key)) || now.toISOString();
}

export async function confirmationStatuses(db, keys) {
  const wanted = [...new Set((Array.isArray(keys) ? keys : []).map((k) => String(k || "").trim()).filter(Boolean))].slice(0, 300);
  if (!wanted.length) return [];
  await ensureConfirmSchema(db);
  const rs = await db.execute({
    sql: `SELECT reminder_key, order_no, service_date, confirmed_at FROM reminder_confirmations
          WHERE reminder_key IN (${wanted.map(() => "?").join(",")})`,
    args: wanted,
  });
  return (rs.rows || []).map((row) => ({
    reminder_key: row.reminder_key ?? row[0],
    order_no: row.order_no ?? row[1],
    service_date: row.service_date ?? row[2],
    confirmed_at: row.confirmed_at ?? row[3],
  }));
}

function page(title, bodyHtml, status = 200) {
  const html = `<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>檸檬家事｜服務提醒確認</title>
<style>body{font-family:-apple-system,"PingFang TC","Noto Sans TC",sans-serif;background:#f6f7f5;margin:0;color:#222}
main{max-width:420px;margin:12vh auto;padding:28px 24px;background:#fff;border-radius:16px;box-shadow:0 2px 12px rgba(0,0,0,.08);text-align:center}
h1{font-size:20px;margin:0 0 16px}p{font-size:16px;line-height:1.7;margin:8px 0}.muted{color:#777;font-size:13px}
button{margin-top:20px;width:100%;padding:16px;font-size:18px;border:0;border-radius:12px;background:#06c755;color:#fff}</style>
</head><body><main><h1>${title}</h1>${bodyHtml}</main></body></html>`;
  return new Response(html, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}

/** 確認頁：GET 只顯示，POST 才記錄。 */
export async function handleConfirm(request, env, pathname, connectDb, now = new Date()) {
  if (!env.REMINDER_API_KEY) return page("暫時無法使用", "<p>系統尚未完成設定，請直接在 LINE 回覆「已收到」，謝謝您。</p>", 503);
  const parsed = parseConfirmPath(pathname);
  const invalid = () => page("連結無效", "<p>這個連結不正確，請直接在 LINE 回覆「已收到」，謝謝您。</p>", 404);
  if (!parsed) return invalid();
  const expected = await confirmSignature(env.REMINDER_API_KEY, parsed.orderNo, parsed.serviceDate);
  if (!sameText(expected, parsed.signature)) return invalid();

  const info = `<p>服務日期：${serviceDateLabel(parsed.serviceDate)}</p><p class="muted">訂單編號 ${parsed.orderNo}</p>`;
  if (request.method === "POST") {
    if (isExpired(parsed.serviceDate, now)) return page("提醒已過期", `${info}<p>這則提醒的服務日期已過。</p>`, 410);
    await recordConfirmation(connectDb(env), parsed.orderNo, parsed.serviceDate, now);
    return page("已確認收到，謝謝您！", `${info}<p>專員會在服務前 5-10 分鐘與您聯繫。</p>`);
  }
  if (request.method !== "GET" && request.method !== "HEAD") return page("連結無效", "", 405);
  if (isExpired(parsed.serviceDate, now)) return page("提醒已過期", `${info}<p>這則提醒的服務日期已過。</p>`, 410);
  return page(
    "檸檬家事 服務提醒",
    `${info}<p>請按下方按鈕，讓我們知道您已收到提醒。</p><form method="post"><button type="submit">確認收到</button></form>`,
  );
}
