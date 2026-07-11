import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = fs.readFileSync(new URL("../lib/ws-client.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { CompanionWsClient } = await import(moduleUrl);

class FakeWebSocket {
  static OPEN = 1;
  static instances = [];

  readyState = 0;
  sent = [];

  constructor(url) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  receive(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  send(payload) {
    this.sent.push(JSON.parse(payload));
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

test("socket open defaults to Pi-only runtime auth", () => {
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = FakeWebSocket;
  FakeWebSocket.instances = [];

  try {
    const client = new CompanionWsClient("ws://runtime.test");
    const statuses = [];
    const confirmations = [];
    client.on("_status", ({ status }) => statuses.push(status));
    client.on("connected", (payload) => confirmations.push(payload));

    client.connect("signed-token");
    const socket = FakeWebSocket.instances[0];
    socket.open();

    assert.deepEqual(socket.sent, [{
      type: "auth",
      token: "signed-token",
      session_id: null,
      agent_runtime: "pi_experimental",
    }]);
    assert.deepEqual(statuses, []);
    assert.deepEqual(confirmations, []);

    socket.receive({
      type: "connected",
      session_id: "session-1",
      agent_runtime: "pi_experimental",
    });

    assert.deepEqual(statuses, []);
    assert.equal(confirmations[0].agent_runtime, "pi_experimental");
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});

test("explicit disconnect drops stale events from the previous runtime", () => {
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = FakeWebSocket;
  FakeWebSocket.instances = [];

  try {
    const client = new CompanionWsClient("ws://runtime.test");
    const statuses = [];
    const confirmations = [];
    client.on("_status", ({ status }) => statuses.push(status));
    client.on("connected", (payload) => confirmations.push(payload));

    client.connect("signed-token", undefined, undefined, "pi_experimental");
    const socket = FakeWebSocket.instances[0];
    socket.open();
    client.disconnect();
    socket.receive({
      type: "connected",
      session_id: "stale-session",
      agent_runtime: "pi_experimental",
    });

    assert.deepEqual(statuses, []);
    assert.deepEqual(confirmations, []);
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});
