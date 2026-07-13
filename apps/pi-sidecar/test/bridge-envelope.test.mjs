import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import http from "node:http";
import test from "node:test";

process.env.PI_ENABLE_TOOLS = "0";
process.env.PI_SIDECAR_PORT = "0";

const { bindClientAbort, createRequestHandler, server: sidecarServer } = await import("../server.mjs");

test.after(() => new Promise((resolve) => sidecarServer.close(resolve)));

function listen(server) {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
}

function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

test("tool bridge sends trusted top-level query and idempotency envelope", () => {
  const source = readFileSync(new URL("../server.mjs", import.meta.url), "utf8");
  assert.match(source, /query:\s*ctx\.userText/);
  assert.match(source, /idempotency_key:\s*ctx\.traceId/);
  assert.doesNotMatch(source, /display_text:\s*`tool bridge unreachable/);
  assert.doesNotMatch(source, /data:\s*\{[^}]*url/s);
});

test("client response close aborts provider agent and tool bridge after body consumption", async () => {
  let providerAborted = false;
  let bridgeAborted = false;
  let requestBodyConsumed = false;
  let resolveAbort;
  const aborted = new Promise((resolve) => { resolveAbort = resolve; });
  const lifecycleServer = http.createServer((req, res) => {
    req.resume();
    req.once("end", () => {
      requestBodyConsumed = true;
      const controller = new AbortController();
      bindClientAbort(req, res, controller);
      controller.signal.addEventListener("abort", () => {
        providerAborted = true;
        resolveAbort();
      });
      controller.signal.addEventListener("abort", () => { bridgeAborted = true; });
      res.writeHead(200, { "Content-Type": "application/x-ndjson" });
      res.write('{"type":"text_delta","delta":"started"}\n');
    });
  });
  await listen(lifecycleServer);

  await new Promise((resolve, reject) => {
    const req = http.request({
      host: "127.0.0.1",
      port: lifecycleServer.address().port,
      method: "POST",
    });
    req.on("error", reject);
    req.on("response", (res) => {
      res.once("data", () => {
        res.destroy();
        req.destroy();
        resolve();
      });
    });
    req.end("request body");
  });
  await Promise.race([
    aborted,
    new Promise((_, reject) => setTimeout(() => reject(new Error("abort timeout")), 500)),
  ]);
  await close(lifecycleServer);

  assert.equal(requestBodyConsumed, true);
  assert.equal(providerAborted, true);
  assert.equal(bridgeAborted, true);
});

test("normal completed response does not abort provider or tool bridge signal", async () => {
  let aborted = false;
  const lifecycleServer = http.createServer((req, res) => {
    req.resume();
    req.once("end", () => {
      const controller = new AbortController();
      bindClientAbort(req, res, controller);
      controller.signal.addEventListener("abort", () => { aborted = true; });
      res.end("done");
    });
  });
  await listen(lifecycleServer);
  await new Promise((resolve, reject) => {
    http.get({ host: "127.0.0.1", port: lifecycleServer.address().port }, (res) => {
      res.resume();
      res.once("end", resolve);
    }).on("error", reject);
  });
  await new Promise((resolve) => setImmediate(resolve));
  await close(lifecycleServer);
  assert.equal(aborted, false);
});

test("tool-enabled non-stream request keeps real client lifecycle separate from buffered output", async () => {
  let receivedRealRequest = false;
  let receivedRealResponse = false;
  let receivedBufferedOutput = false;
  let aborted = false;
  const lifecycleServer = http.createServer(createRequestHandler({
    enableTools: true,
    async streamAgentChatImpl({ req, res, output, body }) {
      receivedRealRequest = req instanceof http.IncomingMessage;
      receivedRealResponse = res instanceof http.ServerResponse;
      receivedBufferedOutput = output !== res;
      assert.equal(body.stream, true);
      const controller = new AbortController();
      const cleanup = bindClientAbort(req, res, controller);
      controller.signal.addEventListener("abort", () => { aborted = true; });
      output.write(`${JSON.stringify({ type: "text_delta", delta: "buffered reply" })}\n`);
      output.write(`${JSON.stringify({ type: "done", tools_used: ["caretask"] })}\n`);
      output.end();
      cleanup();
    },
  }));
  await listen(lifecycleServer);

  const response = await new Promise((resolve, reject) => {
    const req = http.request({
      host: "127.0.0.1",
      port: lifecycleServer.address().port,
      path: "/v1/chat",
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString("utf8") }));
    });
    req.on("error", reject);
    req.end(JSON.stringify({
      stream: false,
      messages: [{ role: "user", content: "set a reminder" }],
    }));
  });
  await close(lifecycleServer);

  assert.equal(response.status, 200);
  assert.deepEqual(JSON.parse(response.body), {
    type: "text",
    text: "buffered reply",
    tools_used: ["caretask"],
  });
  assert.equal(receivedRealRequest, true);
  assert.equal(receivedRealResponse, true);
  assert.equal(receivedBufferedOutput, true);
  assert.equal(aborted, false);
});

test("tool-enabled non-stream client disconnect aborts real lifecycle without flushing buffered output", async () => {
  let resolveStarted;
  let resolveAborted;
  const started = new Promise((resolve) => { resolveStarted = resolve; });
  const aborted = new Promise((resolve) => { resolveAborted = resolve; });
  let workPending = false;
  let bufferedWrites = 0;
  let outputEnded = false;
  let finalResponseWrites = 0;
  let remainingRequestAbortListeners = -1;
  let remainingResponseCloseListeners = -1;
  let remainingResponseFinishListeners = -1;
  let initialRequestAbortListeners = -1;
  let initialResponseCloseListeners = -1;
  let initialResponseFinishListeners = -1;
  const lifecycleServer = http.createServer(createRequestHandler({
    enableTools: true,
    async streamAgentChatImpl({ req, res, output }) {
      workPending = true;
      const originalWriteHead = res.writeHead.bind(res);
      const originalResponseEnd = res.end.bind(res);
      res.writeHead = (...args) => {
        finalResponseWrites += 1;
        return originalWriteHead(...args);
      };
      res.end = (...args) => {
        finalResponseWrites += 1;
        return originalResponseEnd(...args);
      };
      const originalWrite = output.write.bind(output);
      const originalEnd = output.end.bind(output);
      output.write = (...args) => {
        bufferedWrites += 1;
        return originalWrite(...args);
      };
      output.end = (...args) => {
        outputEnded = true;
        return originalEnd(...args);
      };
      initialRequestAbortListeners = req.listenerCount("aborted");
      initialResponseCloseListeners = res.listenerCount("close");
      initialResponseFinishListeners = res.listenerCount("finish");
      const controller = new AbortController();
      const cleanup = bindClientAbort(req, res, controller);
      resolveStarted();
      await new Promise((resolve) => {
        controller.signal.addEventListener("abort", () => {
          resolveAborted();
          resolve();
        }, { once: true });
      });
      cleanup();
      workPending = false;
      remainingRequestAbortListeners = req.listenerCount("aborted");
      remainingResponseCloseListeners = res.listenerCount("close");
      remainingResponseFinishListeners = res.listenerCount("finish");
    },
  }));
  await listen(lifecycleServer);

  const clientRequest = http.request({
    host: "127.0.0.1",
    port: lifecycleServer.address().port,
    path: "/v1/chat",
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  clientRequest.on("error", () => {});
  clientRequest.end(JSON.stringify({
    stream: false,
    messages: [{ role: "user", content: "set a reminder" }],
  }));
  await started;
  clientRequest.destroy();
  await Promise.race([
    aborted,
    new Promise((_, reject) => setTimeout(() => reject(new Error("abort timeout")), 500)),
  ]);
  await new Promise((resolve) => setImmediate(resolve));
  await close(lifecycleServer);

  assert.equal(workPending, false);
  assert.equal(bufferedWrites, 0);
  assert.equal(outputEnded, false);
  assert.equal(finalResponseWrites, 0);
  assert.equal(remainingRequestAbortListeners, initialRequestAbortListeners);
  assert.equal(remainingResponseCloseListeners, initialResponseCloseListeners);
  assert.equal(remainingResponseFinishListeners, initialResponseFinishListeners);
});
