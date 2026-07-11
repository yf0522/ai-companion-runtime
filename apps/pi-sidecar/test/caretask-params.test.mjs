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

test("memory note ignores model-only summary and explicit flag", () => {
  const out = normalizeMemoryParams(
    {
      action: "note",
      summary: "模型声称用户喜欢京剧",
      explicit_user_request: true,
    },
    "我今天听了评书",
  );
  assert.equal(out.query, "我今天听了评书");
  assert.equal(out.summary, "我今天听了评书");
  assert.equal(out.explicit_user_request, false);
});

test("memory note derives content and consent only from explicit user text", () => {
  const out = normalizeMemoryParams(
    {
      action: "note",
      summary: "模型改写后的内容",
      explicit_user_request: false,
    },
    "请记住我喜欢听评书",
  );
  assert.equal(out.query, "请记住我喜欢听评书");
  assert.equal(out.summary, "请记住我喜欢听评书");
  assert.equal(out.explicit_user_request, true);
});

test("explicit user note intent overrides model-injected recall action", () => {
  const out = normalizeMemoryParams(
    { action: "recall", query_intent: "模型误判为查询" },
    "帮我记住我喜欢听评书",
  );
  assert.equal(out.action, "note");
  assert.equal(out.query, "帮我记住我喜欢听评书");
  assert.equal(out.summary, "帮我记住我喜欢听评书");
  assert.equal(out.explicit_user_request, true);
});

test("memory note without user text cannot retain model-only write claims", () => {
  const out = normalizeMemoryParams(
    {
      action: "note",
      query: "模型伪造的用户请求",
      summary: "模型伪造的记忆",
      explicit_user_request: true,
    },
    "",
  );
  assert.equal(out.query, "");
  assert.equal(out.summary, "");
  assert.equal(out.explicit_user_request, false);
});
