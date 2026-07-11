import assert from "node:assert/strict";
import test from "node:test";

import {
  authoritativeToolResultText,
  authoritativeToolShouldTerminate,
  careTaskShouldTerminate,
} from "../tool-policy.mjs";

test("successful CareTask results terminate model follow-up", () => {
  assert.equal(careTaskShouldTerminate("caretask", "success"), true);
});

test("successful contact results terminate model follow-up", () => {
  assert.equal(authoritativeToolShouldTerminate("contact", "success"), true);
});

test("clarification, failures, and other tools keep the agent loop active", () => {
  assert.equal(careTaskShouldTerminate("caretask", "needs_clarification"), false);
  assert.equal(authoritativeToolShouldTerminate("contact", "failed"), false);
  assert.equal(careTaskShouldTerminate("weather", "success"), false);
});

test("non-stream responses select authoritative CareTask and contact tool text", () => {
  assert.equal(
    authoritativeToolResultText({
      type: "tool_result",
      tool: "contact",
      status: "success",
      text: "请求已排队，送达待确认。",
    }),
    "请求已排队，送达待确认。",
  );
  assert.equal(
    authoritativeToolResultText({
      type: "tool_result",
      tool: "contact",
      status: "failed",
      text: "失败",
    }),
    "失败",
  );
  assert.equal(
    authoritativeToolResultText({
      type: "tool_result",
      tool: "memory",
      status: "success",
      text: "记住了",
    }),
    "",
  );
});
