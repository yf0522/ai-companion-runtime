import assert from "node:assert/strict";
import test from "node:test";

import { normalizeCareTaskParams } from "../caretask-params.mjs";

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

test("keeps genuine list requests unchanged", () => {
  assert.deepEqual(
    normalizeCareTaskParams({ action: "list" }, "我有哪些照护任务"),
    { action: "list", query: "我有哪些照护任务" },
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
