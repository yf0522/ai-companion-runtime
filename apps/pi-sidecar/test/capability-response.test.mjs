import assert from "node:assert/strict";
import test from "node:test";

import {
  capabilityResponseFor,
  ELDER_CAPABILITY_RESPONSE,
} from "../capability-response.mjs";

test("capability questions receive one deterministic elder-facing response", () => {
  for (const message of [
    "你有哪些tools?",
    "你有哪些 ToOlS？",
    "你能做什么",
    "你可以做什么呀",
    "你能做啥呢",
    "你都能干些什么",
    "你能做哪些事情",
    "有哪些功能",
    "有哪些功能呢？",
    "请介绍一下你的工具",
    "你有哪些 FUNCTIONS？",
    "What TOOLS do YOU have?",
    "What 功能 do YOU have？",
    "WHAT can you DO",
  ]) {
    assert.equal(capabilityResponseFor(message), ELDER_CAPABILITY_RESPONSE, message);
  }
});

test("capability response contains product language and no internal vocabulary", () => {
  assert.match(ELDER_CAPABILITY_RESPONSE, /照护事项/);
  assert.match(ELDER_CAPABILITY_RESPONSE, /联系家人/);
  assert.match(ELDER_CAPABILITY_RESPONSE, /长期偏好/);
  assert.doesNotMatch(
    ELDER_CAPABILITY_RESPONSE,
    /CareTask|Memory|Contact|tools?|functions?|schema|status|工具|函数|模式|状态/i,
  );
});

test("normal conversation is not intercepted", () => {
  for (const message of [
    "今天天气怎么样",
    "提醒我晚上八点吃药",
    "请联系家人",
    "记住我喜欢喝热水",
    "这个工具箱放在哪里",
    "你知道这个工具有什么用吗",
    "你能告诉我这个功能怎么用吗",
  ]) {
    assert.equal(capabilityResponseFor(message), "", message);
  }
});
