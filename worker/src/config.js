/**
 * 只記錄模式：訊息照常寫入資料庫，但不做風險標記、關鍵字回覆與 AI 回覆。
 * 預設開啟（沒設定 RECORD_ONLY 也視為開啟），避免重新開啟 Webhook 時自動回覆客人。
 * 只有明確設定 RECORD_ONLY = "off" 才恢復自動回覆流程。
 */
export function isRecordOnly(env) {
  return String(env?.RECORD_ONLY ?? "on").trim().toLowerCase() !== "off";
}
