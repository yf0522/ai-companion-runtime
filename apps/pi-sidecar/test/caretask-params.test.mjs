import assert from "node:assert/strict";
import test from "node:test";

import {
  isExplicitFamilyContactRequest,
  normalizeCareTaskParams,
  normalizeContactParams,
  normalizeMemoryParams,
} from "../caretask-params.mjs";

test("single CareTask mutations require direct speech-act authorization", () => {
  for (const query of [
    "请问如何取消吃药提醒",
    "我只是举例：取消吃药提醒",
    "不要取消吃药提醒",
    "如果我要取消吃药提醒怎么办",
    "医生问我是否取消吃药提醒",
    "她说“提醒我晚上8点吃药”",
    "我没完成吃药任务",
    "我不是要取消吃药提醒",
    "我不想取消吃药提醒",
    "我不打算延后吃药提醒",
    "我不会建立吃药提醒",
  ]) {
    assert.equal(normalizeCareTaskParams({ action: "cancel" }, query).action, "clarify", query);
  }
  for (const [query, action] of [
    ["请完成降压药", "complete"],
    ["取消吃药提醒", "cancel"],
    ["不要提醒我吃药", "cancel"],
    ["提醒我晚上8点吃药", "create"],
    ["明天晚上八点吃药", "create"],
    ["后天上午九点复诊", "create"],
    ["每天晚上八点吃降糖药", "create"],
    ["把降压药提醒延后30分钟", "snooze"],
    ["我吃了药", "complete"],
    ["关掉提醒", "cancel"],
    ["建立提醒", "create"],
  ]) {
    assert.equal(normalizeCareTaskParams({ action: "list" }, query).action, action, query);
  }
});

test("Python and JavaScript CareTask speech-act parity corpus", () => {
  for (const [query, expected] of [
    ["请完成降压药", "complete"],
    ["取消吃药提醒", "cancel"],
    ["不要提醒我吃药", "cancel"],
    ["提醒我晚上8点吃药", "create"],
    ["明天晚上八点吃药", "create"],
    ["把降压药提醒延后30分钟", "snooze"],
    ["我吃了药", "complete"],
    ["吃完降压药", "complete"],
    ["降压药打卡", "complete"],
    ["医生问我取消吃药提醒", "clarify"],
    ["妈妈说取消吃药提醒", "clarify"],
    ["我明天晚上八点吃药", "list"],
    ["今天有什么任务", "list"],
  ]) {
    assert.equal(
      normalizeCareTaskParams({ action: "create" }, query).action,
      expected,
      query,
    );
  }
});

test("CareTask normalizer drops model-controlled semantic arguments", () => {
  const result = normalizeCareTaskParams(
    {
      action: "snooze",
      task_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      title: "模型伪造任务",
      task_type: "appointment",
      due_at: "2039-01-01T00:00:00",
      minutes: 1440,
      notes: "模型伪造备注",
      schedule_type: "once",
    },
    "把降压药提醒延后30分钟",
  );

  assert.deepEqual(result, {
    action: "snooze",
    query: "把降压药提醒延后30分钟",
  });
});

test("scheduled CareTask creation rejects questions, hypotheticals, reports, quotes, and ordinary mentions", () => {
  for (const query of [
    "我明天晚上八点吃药",
    "明天我会吃药",
    "明天如果不舒服就吃药",
    "明天医生让我晚上八点吃药",
    "明天新闻说晚上八点吃药",
    "明天“晚上八点吃药”",
    "如果明天晚上八点吃药会怎么样",
    "明天晚上八点吃药吗？",
    "新闻里说明天晚上八点吃药",
    "她说“明天晚上八点吃药”",
  ]) {
    assert.notEqual(
      normalizeCareTaskParams({ action: "create" }, query).action,
      "create",
      query,
    );
  }
});

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

test("overrides model create for read-only care task questions", () => {
  for (const query of ["今日任务", "我问你今天有什么照护任务", "我今天需要做什么", "吃药"]) {
    assert.deepEqual(
      normalizeCareTaskParams({ action: "create", title: "模型误建任务" }, query),
      { action: "list", query, scope: "today" },
    );
  }
});

test("keeps explicit reminder creation as a write", () => {
  assert.deepEqual(
    normalizeCareTaskParams({ action: "create" }, "提醒我晚上八点吃药"),
    { action: "create", query: "提醒我晚上八点吃药" },
  );
});

test("read-only text overrides any model-selected care task mutation", () => {
  for (const action of ["create", "complete", "cancel", "snooze"]) {
    assert.deepEqual(
      normalizeCareTaskParams({ action }, "我今天有什么照护任务"),
      { action: "list", query: "我今天有什么照护任务", scope: "today" },
    );
  }
});

test("read-only phrasing wins over mutation words", () => {
  assert.deepEqual(
    normalizeCareTaskParams({ action: "cancel" }, "今天取消了哪些任务"),
    { action: "list", query: "今天取消了哪些任务", scope: "today" },
  );
  assert.deepEqual(
    normalizeCareTaskParams({ action: "create" }, "今天有什么安排"),
    { action: "list", query: "今天有什么安排", scope: "today" },
  );
});

test("contact params keep only the trusted raw user request", () => {
  assert.deepEqual(
    normalizeContactParams(
      {
        action: "delivered",
        query: "模型改写",
        recipient: "attacker@example.com",
        user_id: "spoofed-user",
      },
      "我想让家人知道我需要帮助",
    ),
    {
      action: "request_contact",
      query: "我想让家人知道我需要帮助",
    },
  );
});

test("contact side effects require an explicit non-negated family request", () => {
  assert.equal(isExplicitFamilyContactRequest("我想让家人知道我需要帮助"), true);
  assert.equal(isExplicitFamilyContactRequest("请家人联系我"), true);
  assert.equal(isExplicitFamilyContactRequest("让女儿给我打电话"), true);
  assert.equal(isExplicitFamilyContactRequest("请通知家人我需要帮助"), true);
  assert.equal(isExplicitFamilyContactRequest("我今天有点累"), false);
  assert.equal(isExplicitFamilyContactRequest("我不想让家人知道"), false);
  assert.equal(isExplicitFamilyContactRequest("我已经告诉家人了"), false);
  assert.equal(isExplicitFamilyContactRequest("医生让我联系家人"), false);
  assert.equal(isExplicitFamilyContactRequest("我刚联系过女儿"), false);
  assert.equal(isExplicitFamilyContactRequest("联系家人了吗"), false);
  assert.equal(isExplicitFamilyContactRequest("我想告诉家人最近挺好的"), false);
  assert.equal(isExplicitFamilyContactRequest("联系家人"), true);
  assert.equal(isExplicitFamilyContactRequest("我想请你通知女儿"), true);
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
