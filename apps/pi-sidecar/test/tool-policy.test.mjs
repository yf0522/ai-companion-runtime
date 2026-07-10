import assert from "node:assert/strict";
import test from "node:test";

import { careTaskShouldTerminate } from "../tool-policy.mjs";

test("successful CareTask results terminate model follow-up", () => {
  assert.equal(careTaskShouldTerminate("caretask", "success"), true);
});

test("clarification and other tools keep the agent loop active", () => {
  assert.equal(careTaskShouldTerminate("caretask", "needs_clarification"), false);
  assert.equal(careTaskShouldTerminate("weather", "success"), false);
});
