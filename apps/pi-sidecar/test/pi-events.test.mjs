import assert from "node:assert/strict";
import test from "node:test";

import { assistantErrorMessage, ASSISTANT_ERROR_MESSAGE } from "../pi-events.mjs";

test("redacts provider errors from failed assistant messages", () => {
  assert.equal(
    assistantErrorMessage({
      type: "message_end",
      message: {
        role: "assistant",
        stopReason: "error",
        errorMessage: "model unavailable",
      },
    }),
    ASSISTANT_ERROR_MESSAGE,
  );
  assert.doesNotMatch(ASSISTANT_ERROR_MESSAGE, /model unavailable|provider|token|https?:/i);
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
