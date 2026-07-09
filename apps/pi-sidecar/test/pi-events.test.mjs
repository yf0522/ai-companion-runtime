import assert from "node:assert/strict";
import test from "node:test";

import { assistantErrorMessage } from "../pi-events.mjs";

test("returns provider errors from failed assistant messages", () => {
  assert.equal(
    assistantErrorMessage({
      type: "message_end",
      message: {
        role: "assistant",
        stopReason: "error",
        errorMessage: "model unavailable",
      },
    }),
    "model unavailable",
  );
});

test("ignores successful and non-assistant message endings", () => {
  assert.equal(
    assistantErrorMessage({
      type: "message_end",
      message: { role: "assistant", stopReason: "stop" },
    }),
    null,
  );
  assert.equal(
    assistantErrorMessage({
      type: "message_end",
      message: { role: "user", stopReason: "error" },
    }),
    null,
  );
});
