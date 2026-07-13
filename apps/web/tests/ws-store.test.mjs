import assert from "node:assert/strict";
import test from "node:test";

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

function begin(user, trace = `trace-${user}`) {
  useChatStore.getState().activateUser(user);
  useChatStore.getState().clearMessages();
  useChatStore.getState().startAssistantMessage(trace);
  return trace;
}

test("store preserves every explicit execution status instead of normalizing to calling", () => {
  const statuses = ["calling", "in_progress", "cancelled", "interrupted"];
  for (const status of statuses) {
    const traceId = begin(`normalize-${status}`);
    useChatStore.getState().setToolStatus(traceId, "caretask", status);
    assert.equal(useChatStore.getState().messages.at(-1)?.toolsUsed?.[0]?.status, status);
  }
});

test("missing-final fallback stops every terminal state but not active or in-progress work", () => {
  const states = {
    calling: false,
    in_progress: false,
    success: true,
    failed: true,
    timeout: true,
    needs_clarification: true,
    cancelled: true,
    interrupted: true,
  };
  for (const [status, shouldStop] of Object.entries(states)) {
    const traceId = begin(`fallback-${status}`);
    useChatStore.getState().setToolStatus(traceId, "caretask", status);
    useChatStore.getState().completeToolTurnFallback();
    const state = useChatStore.getState();
    assert.equal(state.isStreaming, !shouldStop, status);
    assert.equal(state.messages.at(-1)?.status, shouldStop ? "complete" : "streaming", status);
  }
});

test("cancelled and interrupted results stop streaming even when no final timer is armed", () => {
  for (const status of ["cancelled", "interrupted"]) {
    const traceId = begin(`result-${status}`);
    useChatStore.getState().setToolResult({
      traceId,
      tool: "caretask",
      status,
      action: "caretask_batch",
      text: status === "cancelled" ? "1. 完成：未执行" : "1. 完成：未完成",
    });
    const state = useChatStore.getState();
    assert.equal(state.isStreaming, false, status);
    assert.equal(state.messages.at(-1)?.status, "complete", status);
  }
});

test("late finals enrich terminal results without reviving or replacing their outcome", () => {
  for (const status of ["cancelled", "interrupted"]) {
    const traceId = begin(`late-${status}`);
    useChatStore.getState().setToolResult({
      traceId,
      tool: "caretask",
      status,
      action: "caretask_batch",
      text: "1. 完成：未完成\n2. 查看：未执行",
      data: { receipts: [{ index: 0, action: "complete", status: "failed" }] },
    });
    useChatStore.getState().finalizeMessage({
      traceId,
      messageId: `final-${status}`,
      ttftMs: 10,
      totalLatencyMs: 25,
      toolsUsed: [{ tool: "caretask", status: "calling", action: "caretask_batch" }],
      memoryUpdated: false,
    });
    const state = useChatStore.getState();
    const tool = state.messages.at(-1)?.toolsUsed?.[0];
    assert.equal(state.isStreaming, false, status);
    assert.equal(state.messages.at(-1)?.id, `final-${status}`, status);
    assert.equal(tool?.status, status, status);
    assert.equal(tool?.displayText, "1. 完成：未完成\n2. 查看：未执行", status);
    assert.deepEqual(tool?.data?.receipts, [{ index: 0, action: "complete", status: "failed" }], status);
  }
});

test("a late successful final advances in-progress without losing receipt evidence", () => {
  const traceId = begin("late-in-progress");
  useChatStore.getState().setToolResult({
    traceId,
    tool: "caretask",
    status: "in_progress",
    action: "caretask_batch",
    data: { receipts: [{ index: 0, action: "complete", status: "completed" }] },
  });
  assert.equal(useChatStore.getState().isStreaming, true);

  useChatStore.getState().finalizeMessage({
    traceId,
    messageId: "final-in-progress",
    ttftMs: 8,
    totalLatencyMs: 20,
    toolsUsed: [{ tool: "caretask", status: "success", action: "caretask_batch" }],
    memoryUpdated: false,
  });
  const tool = useChatStore.getState().messages.at(-1)?.toolsUsed?.[0];
  assert.equal(tool?.status, "success");
  assert.deepEqual(tool?.data?.receipts, [{ index: 0, action: "complete", status: "completed" }]);
  assert.equal(useChatStore.getState().isStreaming, false);
});

test("an old trace final cannot finalize or overwrite the newer streaming trace", () => {
  begin("late-final-race", "trace-old");
  useChatStore.getState().startAssistantMessage("trace-new");
  const newerId = useChatStore.getState().messages.at(-1).id;

  useChatStore.getState().finalizeMessage({
    traceId: "trace-old",
    messageId: "old-final-id",
    ttftMs: 1,
    totalLatencyMs: 2,
    toolsUsed: [],
    memoryUpdated: false,
  });

  let state = useChatStore.getState();
  assert.equal(state.currentTraceId, "trace-new");
  assert.equal(state.isStreaming, true);
  assert.equal(state.messages.at(-1).traceId, "trace-new");
  assert.equal(state.messages.at(-1).id, newerId);
  assert.equal(state.messages.at(-1).status, "streaming");

  useChatStore.getState().finalizeMessage({
    traceId: "trace-new",
    messageId: "new-final-id",
    ttftMs: 3,
    totalLatencyMs: 4,
    toolsUsed: [],
    memoryUpdated: false,
  });
  state = useChatStore.getState();
  assert.equal(state.currentTraceId, null);
  assert.equal(state.isStreaming, false);
  assert.equal(state.messages.at(-1).id, "new-final-id");
  assert.equal(state.messages.at(-1).status, "complete");
});

test("old trace frames cannot mutate or terminate a newer turn", () => {
  begin("stale-frames", "trace-old");
  useChatStore.getState().startAssistantMessage("trace-new");
  useChatStore.getState().appendDelta("trace-old", "stale delta");
  useChatStore.getState().setToolStatus("trace-old", "caretask", "failed");
  useChatStore.getState().setRiskAlert("trace-old", "high", "stale risk");
  useChatStore.getState().setError("trace-old", "stale error");
  useChatStore.getState().acknowledgeCancellation("trace-old");

  const state = useChatStore.getState();
  const current = state.messages.at(-1);
  assert.equal(state.currentTraceId, "trace-new");
  assert.equal(state.isStreaming, true);
  assert.equal(current?.content, "");
  assert.equal(current?.status, "streaming");
  assert.deepEqual(current?.toolsUsed, []);
  assert.equal(current?.riskAlert, undefined);
});

test("terminal receipt evidence survives device-local history persistence", () => {
  const traceId = begin("persist-receipts");
  useChatStore.getState().setToolResult({
    traceId,
    tool: "caretask",
    status: "interrupted",
    action: "caretask_batch",
    data: {
      receipts: [
        { index: 0, action: "complete", status: "completed", result: { title: "吃降糖药" }, private: "drop" },
        { index: 1, action: "snooze", status: "failed" },
        { index: 2, action: "list", status: "unattempted" },
      ],
    },
  });
  useChatStore.getState().finalizeMessage({
    traceId,
    messageId: "final-persist-receipts",
    ttftMs: 9,
    totalLatencyMs: 21,
    toolsUsed: [],
    memoryUpdated: false,
  });

  const persisted = storage.get("companion-chat");
  assert.match(persisted, /"status":"completed"/);
  assert.match(persisted, /"status":"failed"/);
  assert.match(persisted, /"status":"unattempted"/);
  assert.match(persisted, /吃降糖药/);
  assert.doesNotMatch(persisted, /"private"|"drop"/);
});

test("device-local receipt persistence bounds arrays and elder-facing titles", () => {
  const traceId = begin("persist-bounded-receipts");
  useChatStore.getState().setToolResult({
    traceId,
    tool: "caretask",
    status: "interrupted",
    action: "caretask_batch",
    data: {
      receipts: Array.from({ length: 25 }, (_, index) => ({
        index,
        action: "complete",
        status: "completed",
        result: { title: "药".repeat(200), titles: Array(15).fill("复诊".repeat(80)) },
      })),
    },
  });

  const persisted = JSON.parse(storage.get("companion-chat"));
  const receipts = persisted.state.messagesByUser["persist-bounded-receipts"]
    .at(-1).toolsUsed[0].data.receipts;
  assert.equal(receipts.length, 20);
  assert.equal(receipts[0].result.title.length, 120);
  assert.equal(receipts[0].result.titles.length, 10);
  assert.equal(receipts[0].result.titles[0].length, 120);
});
