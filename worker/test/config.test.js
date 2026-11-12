import test from "node:test";
import assert from "node:assert/strict";

import { isRecordOnly } from "../src/config.js";

test("record-only is on by default and when unset", () => {
  assert.equal(isRecordOnly({}), true);
  assert.equal(isRecordOnly(undefined), true);
  assert.equal(isRecordOnly({ RECORD_ONLY: "on" }), true);
  assert.equal(isRecordOnly({ RECORD_ONLY: "" }), true);
});

test("only an explicit off restores auto replies", () => {
  assert.equal(isRecordOnly({ RECORD_ONLY: "off" }), false);
  assert.equal(isRecordOnly({ RECORD_ONLY: " OFF " }), false);
  assert.equal(isRecordOnly({ RECORD_ONLY: "false" }), true);
});
