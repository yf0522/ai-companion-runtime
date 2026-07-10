import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeCareTaskParams,
  normalizeMemoryParams,
} from "../caretask-params.mjs";

test("corrects list to cancel for explicit cancellation intent", () => {
  assert.deepEqual(
    normalizeCareTaskParams({ action: "list" }, "取消吃药提醒"),
    { action: "cancel", query: "取消吃药提醒" },
  );
});

test("corrects list to complete for explicit medication completion", () => {
  assert.deepEqual(
    normalizeCareTaskParams({ action: "list" }, "降压药我吃过了"),
    { action: "complete", query: "降压药我吃过了" },
  );
});

test("keeps genuine list requests and defaults scope=today", () => {
  assert.deepEqual(
    normalizeCareTaskParams({ action: "list" }, "我有哪些照护任务"),
    { action: "list", query: "我有哪些照护任务", scope: "today" },
  );
});

test("uses original user text instead of model-injected schedule text", () => {
  assert.deepEqual(
    normalizeCareTaskParams(
      {
        action: "create",
        query: "2023-11-20 08:00 提醒我吃降糖药",
        due_at: "2023-11-20T08:00:00",
      },
      "提醒我吃降糖药",
    ),
    {
      action: "create",
      query: "提醒我吃降糖药",
      due_at: "2023-11-20T08:00:00",
    },
  );
});

test("memory note from 以后记得 phrasing", () => {
  const out = normalizeMemoryParams({ action: "auto" }, "以后记得我喜欢听评书");
  assert.equal(out.action, "note");
  assert.equal(out.explicit_user_request, true);
  assert.match(out.summary, /评书/);
});

test("memory recall from continuity phrasing", () => {
  const out = normalizeMemoryParams({}, "你还记得我喜欢什么吗");
  assert.equal(out.action, "recall");
  assert.ok(out.query_intent);
});
