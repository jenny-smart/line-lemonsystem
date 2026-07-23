import test from "node:test";
import assert from "node:assert/strict";
import { buildContext, classifyRisk, findRelevantTemplates } from "../src/ai.js";

test("客訴與退費直接轉人工", () => {
  assert.equal(classifyRisk("昨天根本沒清乾淨，我要客訴退費").needsHuman, true);
});

test("取消改期屬人工確認金額的第二層", () => {
  const risk = classifyRisk("我想把下週的服務改期");
  assert.equal(risk.tier, 2);
  assert.equal(risk.needsHuman, false);
});

test("只挑選相關模板以節省 prompt token", () => {
  const templates = findRelevantTemplates("請問沙發水洗多少錢");
  assert.ok(templates.length > 0);
  assert.ok(templates.length <= 3);
  assert.ok(templates.some((item) => item.id.includes("sofa") || item.category.includes("沙發")));
});

test("規則上下文只載入相關區塊", () => {
  const context = buildContext("台北車馬費怎麼算");
  assert.ok(context.rules.transport_fee);
  assert.ok(context.rules.regional_bank_accounts);
  assert.equal(context.rules.refund_process, undefined);
});
