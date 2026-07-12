import assert from "node:assert/strict";
import test from "node:test";

import {
  careTaskStatusLabel,
  isCareTaskActionable,
  isCareTaskActive,
  isTerminalCareTaskStatus,
} from "../lib/care-task-state.ts";
import {
  assistantBodyAfterToolReceipts,
  outcomeReceiptForTool,
} from "../components/elder/outcome-receipt.ts";
import { memoryCorrectionReceipt } from "../app/elder/memory/correction-receipt.ts";

test("canonical CareTask states drive elder labels and activity", () => {
  assert.equal(isCareTaskActive({ status: "pending" }), true);
  assert.equal(isCareTaskActive({ status: "due" }), true);
  assert.equal(isCareTaskActive({ status: "snoozed" }), true);
  assert.equal(isCareTaskActive({ status: "done" }), false);
  assert.equal(isCareTaskActive({ status: "missed" }), false);
  assert.equal(isCareTaskActive({ status: "cancelled" }), false);

  assert.equal(isTerminalCareTaskStatus("done"), true);
  assert.equal(isTerminalCareTaskStatus("missed"), true);
  assert.equal(isTerminalCareTaskStatus("cancelled"), true);
  assert.equal(isCareTaskActionable({ status: "missed" }), true);

  assert.equal(careTaskStatusLabel("pending"), "已安排");
  assert.equal(careTaskStatusLabel("due"), "现在需要处理");
  assert.equal(careTaskStatusLabel("snoozed"), "已延后");
  assert.equal(careTaskStatusLabel("done"), "已完成");
  assert.equal(careTaskStatusLabel("missed"), "已错过");
  assert.equal(careTaskStatusLabel("cancelled"), "已取消");
});

test("legacy task aliases remain truthful while canonical states lead", () => {
  assert.equal(isCareTaskActive({ status: "scheduled" }), true);
  assert.equal(isCareTaskActive({ status: "completed" }), false);
  assert.equal(careTaskStatusLabel("scheduled"), "已安排");
  assert.equal(careTaskStatusLabel("completed"), "已完成");
});

test("memory correction receipt respects the current consent state", () => {
  assert.match(memoryCorrectionReceipt("granted"), /之后会使用新内容/);
  assert.match(memoryCorrectionReceipt("pending"), /同意保留后.*才会使用/);
  assert.match(memoryCorrectionReceipt("legacy_unverified"), /同意保留后.*才会使用/);
  assert.match(memoryCorrectionReceipt("rejected"), /仍不会用于陪伴/);
  assert.match(memoryCorrectionReceipt("granted", "expired"), /保留期已经结束.*仍不会用于陪伴/);
});

test("outcome receipts never expose raw internal tool names", () => {
  const task = outcomeReceiptForTool({
    tool: "caretask",
    status: "success",
    action: "create",
    displayText: "今晚 8 点的降压药提醒已建立。",
    data: { title: "降压药", due_at: "2026-07-11T20:00:00Z" },
  });
  assert.equal(task.title, "照护提醒已建立");
  assert.equal(task.detail, "今晚 8 点的降压药提醒已建立。");
  assert.doesNotMatch(`${task.title}${task.detail}`, /caretask/i);

  const memory = outcomeReceiptForTool({
    tool: "memory",
    status: "success",
    action: "note",
    displayText: "这条内容需要你确认后才会长期保留。",
    data: { status: "pending" },
  });
  assert.equal(memory.title, "这条记忆等待你的同意");
  assert.equal(memory.tone, "pending");

  const failure = outcomeReceiptForTool({ tool: "search", status: "timeout" });
  assert.equal(failure.title, "这次操作没有完成");
  assert.doesNotMatch(`${failure.title}${failure.detail}`, /search/i);

  const list = outcomeReceiptForTool({ tool: "caretask", status: "success", action: "caretask_list" });
  assert.equal(list.title, "已查看照护事项");
  assert.equal(list.tone, "info");
  assert.equal(list.detail, "只读取了当前任务，没有修改任何提醒。");
  assert.doesNotMatch(`${list.title}${list.detail}`, /已建立|已更新/);

  const calling = outcomeReceiptForTool({ tool: "caretask", status: "calling" });
  assert.equal(calling.tone, "loading");

  const recall = outcomeReceiptForTool({
    tool: "memory",
    status: "success",
    action: "memory_recall",
    data: { status: "empty" },
  });
  assert.equal(recall.title, "没有找到可使用的长期记忆");
});

test("read-only task results remain visible as the assistant answer", () => {
  const tools = [{
    tool: "caretask",
    status: "success",
    action: "caretask_list",
    displayText: "您当前的照护任务：\n- 晚上吃药",
  }];
  assert.equal(
    assistantBodyAfterToolReceipts("您当前的照护任务：\n- 晚上吃药", tools),
    "您当前的照护任务：\n- 晚上吃药",
  );
  assert.equal(
    assistantBodyAfterToolReceipts("我再补充一句说明。", tools),
    "我再补充一句说明。",
  );
  assert.equal(
    assistantBodyAfterToolReceipts("您当前的照护任务：\n- 晚上吃药", [{ ...tools[0], status: "failed" }]),
    "您当前的照护任务：\n- 晚上吃药",
  );
  assert.equal(
    assistantBodyAfterToolReceipts("已查看任务，下面是补充说明。", tools),
    "已查看任务，下面是补充说明。",
  );
});

test("runtime selection hydrates the stored Pi choice before connecting", async () => {
  const storage = new Map([["companion.agent_runtime", "pi_experimental"]]);
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
    clear: () => storage.clear(),
    key: (index) => [...storage.keys()][index] ?? null,
    get length() { return storage.size; },
  };
  const { getActiveAgentRuntime, useAgentRuntimeStore } = await import("../stores/agentRuntimeStore.ts");
  useAgentRuntimeStore.setState({ runtime: "harness", hydrated: false });
  assert.equal(getActiveAgentRuntime(), "pi_experimental");
  assert.equal(useAgentRuntimeStore.getState().hydrated, true);
});

test("device-local chat history is partitioned by authenticated user and clearable", async () => {
  const storage = new Map();
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
    clear: () => storage.clear(),
    key: (index) => [...storage.keys()][index] ?? null,
    get length() { return storage.size; },
  };

  const { useChatStore } = await import("../stores/chatStore.ts");
  useChatStore.getState().activateUser("elder-a");
  useChatStore.getState().clearMessages();
  useChatStore.getState().addUserMessage("只属于 A 的消息");

  useChatStore.getState().activateUser("elder-b");
  assert.deepEqual(useChatStore.getState().messages, []);
  useChatStore.getState().addUserMessage("只属于 B 的消息");

  useChatStore.getState().activateUser("elder-a");
  assert.deepEqual(useChatStore.getState().messages.map((item) => item.content), ["只属于 A 的消息"]);
  useChatStore.getState().clearMessages();
  assert.deepEqual(useChatStore.getState().messages, []);

  useChatStore.getState().activateUser("elder-b");
  assert.deepEqual(useChatStore.getState().messages.map((item) => item.content), ["只属于 B 的消息"]);

  useChatStore.getState().activateUser("elder-private");
  useChatStore.getState().startAssistantMessage("trace-secret");
  useChatStore.getState().setToolResult({
    tool: "memory_recall_provider",
    status: "success",
    action: "memory_recall",
    text: "我记得这些：不应写入本机存储的记忆片段",
    data: {
      status: "success",
      consent_status: "granted",
      fragments: ["不应写入本机存储的记忆片段"],
      trace_id: "trace-secret",
      internal_payload: { provider: "private" },
    },
  });
  useChatStore.getState().finalizeMessage({
    traceId: "trace-secret",
    messageId: "assistant-private",
    ttftMs: 12,
    totalLatencyMs: 34,
    toolsUsed: [],
    memoryUpdated: false,
  });
  const persisted = storage.get("companion-chat");
  assert.ok(persisted);
  assert.doesNotMatch(persisted, /不应写入|fragments|trace-secret|trace_id|internal_payload|memory_recall_provider/);
  assert.match(persisted, /"tool":"memory"/);
  assert.match(persisted, /"consent_status":"granted"/);
});

test("terminal tool results stop an orphaned spinner and accept a late final", async () => {
  const { useChatStore } = await import("../stores/chatStore.ts");
  useChatStore.getState().activateUser("elder-tool-fallback");
  useChatStore.getState().clearMessages();
  useChatStore.getState().startAssistantMessage("trace-tool-fallback");
  useChatStore.getState().setToolResult({
    tool: "caretask",
    status: "success",
    action: "caretask_list",
    text: "您当前的照护任务：\n- 吃降糖药",
  });

  useChatStore.getState().completeToolTurnFallback();
  let state = useChatStore.getState();
  assert.equal(state.isStreaming, false);
  assert.equal(state.messages.at(-1)?.status, "complete");
  assert.equal(state.messages.at(-1)?.content, "");

  useChatStore.getState().finalizeMessage({
    traceId: "trace-tool-fallback",
    messageId: "assistant-tool-final",
    ttftMs: 12,
    totalLatencyMs: 34,
    toolsUsed: [{ tool: "caretask", status: "success", action: "caretask_list" }],
    memoryUpdated: false,
  });
  state = useChatStore.getState();
  assert.equal(state.messages.at(-1)?.id, "assistant-tool-final");
  assert.equal(state.messages.at(-1)?.totalLatencyMs, 34);
  assert.equal(state.messages.at(-1)?.status, "complete");
});
