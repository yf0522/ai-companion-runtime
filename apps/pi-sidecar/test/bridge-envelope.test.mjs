import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("tool bridge sends trusted top-level query and idempotency envelope", () => {
  const source = readFileSync(new URL("../server.mjs", import.meta.url), "utf8");
  assert.match(source, /query:\s*ctx\.userText/);
  assert.match(source, /idempotency_key:\s*ctx\.traceId/);
  assert.doesNotMatch(source, /display_text:\s*`tool bridge unreachable/);
  assert.doesNotMatch(source, /data:\s*\{[^}]*url/s);
});

test("request close aborts provider agent and tool bridge work", () => {
  const source = readFileSync(new URL("../server.mjs", import.meta.url), "utf8");
  assert.match(source, /req\?\.once\?\.\("close", abort\)/);
  assert.match(source, /controller\.signal\.addEventListener\("abort", \(\) => agent\.abort\(\)/);
  assert.match(source, /signal:\s*ctx\.signal/);
});
