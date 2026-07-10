import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../components/MessageBubble.tsx", import.meta.url), "utf8");

test("elder presentation translates raw provider failures", () => {
  assert.match(source, /User location is not supported/i);
  assert.match(source, /提醒和安全功能仍然可用/);
  assert.doesNotMatch(source, /return technicalFailure \? content/);
});

test("care task clarification keeps the backend command contract", () => {
  const chatWindow = fs.readFileSync(new URL("../components/ChatWindow.tsx", import.meta.url), "utf8");
  assert.match(chatWindow, /`\$\{action\} \$\{candidate\.title\} id=\$\{candidate\.id\}`/);
});
