import assert from "node:assert/strict";
import test from "node:test";
import {
  formatReadinessDuration,
  mapPlatformReadiness,
} from "../app/ops/_lib/platform-readiness.ts";

const NOW = new Date("2026-07-12T08:30:30Z");

function response(overrides = {}) {
  return {
    contract_version: "operator-platform-readiness.v1",
    scope: "platform",
    status: "ready",
    checked_at: "2026-07-12T08:30:00Z",
    stale_after_seconds: 60,
    future_skew_seconds: 5,
    duration_ms: 12.4,
    checks: [
      {
        id: "redis",
        label: "Redis memory and queue store",
        status: "ready",
        summary: "redis responded",
        duration_ms: 1.3,
        owner: "Platform runtime",
        next_action: "Verify the active Redis URL and authentication profile.",
        runbook: "platform-readiness#redis",
      },
    ],
    ...overrides,
  };
}

test("fresh canonical evidence retains its backend aggregate", () => {
  const view = mapPlatformReadiness(response(), NOW);
  assert.equal(view.state, "ready");
  assert.equal(view.sourceStatus, "ready");
  assert.equal(view.evidenceState, "fresh");
  assert.equal(view.tone, "success");
  assert.equal(view.checkCount, 1);
  assert.equal(view.durationMs, 12.4);
});

test("missing or wrong contract versions fail closed", () => {
  for (const contract_version of [undefined, "operator-platform-readiness.v0", "platform-readiness.v1"]) {
    const view = mapPlatformReadiness(response({ contract_version }), NOW);
    assert.equal(view.state, "unknown");
    assert.equal(view.tone, "unknown");
  }
});

test("list-valued observed evidence is copied and bounded", () => {
  const heads = Array.from({ length: 12 }, (_, index) => `${index}-${"x".repeat(120)}`);
  const payload = response({
    checks: [{ ...response().checks[0], observed: { heads } }],
  });
  const view = mapPlatformReadiness(payload, NOW);
  heads[0] = "mutated-after-map";

  assert.equal(view.state, "ready");
  assert.equal(view.checks[0].observed.length, 1);
  assert.equal(view.checks[0].observed[0].label, "迁移版本");
  assert.doesNotMatch(view.checks[0].observed[0].value, /mutated-after-map/);
  assert.ok(view.checks[0].observed[0].value.length <= 640);
  assert.equal(view.checks[0].observed[0].value.split(" · ").length, 8);
});

test("stale evidence never presents the recorded healthy aggregate as healthy", () => {
  const view = mapPlatformReadiness(response({ checked_at: "2026-07-12T08:28:00Z" }), NOW);
  assert.equal(view.state, "stale");
  assert.equal(view.sourceStatus, "ready");
  assert.equal(view.evidenceState, "stale");
  assert.notEqual(view.tone, "success");
  assert.match(view.title, /过期/);
});

test("missing, invalid, and excessive-future timestamps become unknown", () => {
  for (const checked_at of [undefined, "not-a-date", "2026-07-12T08:30:36Z"]) {
    const view = mapPlatformReadiness(response({ checked_at }), NOW);
    assert.equal(view.state, "unknown");
    assert.equal(view.tone, "unknown");
  }
  assert.equal(
    mapPlatformReadiness(response({ checked_at: "2026-07-12T08:30:35Z" }), NOW).state,
    "ready",
  );
});

test("unknown aggregate, check status, or optimistic inconsistency fails closed", () => {
  const unknownAggregate = mapPlatformReadiness(response({ status: "mystery" }), NOW);
  assert.equal(unknownAggregate.state, "unknown");
  assert.notEqual(unknownAggregate.tone, "success");

  const unknownCheck = mapPlatformReadiness(response({
    checks: [{ ...response().checks[0], status: "mystery" }],
  }), NOW);
  assert.equal(unknownCheck.state, "unknown");
  assert.equal(unknownCheck.checks[0].statusLabel, "状态待确认");

  const inconsistent = mapPlatformReadiness(response({
    status: "ready",
    checks: [{ ...response().checks[0], status: "unsafe_to_serve" }],
  }), NOW);
  assert.equal(inconsistent.state, "unknown");
  assert.notEqual(inconsistent.tone, "success");
});

test("malformed payloads preserve missing numbers as unknown instead of zero", () => {
  for (const payload of [null, {}, response({ checks: [] }), response({ duration_ms: undefined })]) {
    const view = mapPlatformReadiness(payload, NOW);
    assert.equal(view.state, "unknown");
    assert.notEqual(view.tone, "success");
    if (payload === null || payload?.duration_ms === undefined) {
      assert.equal(view.durationMs, null);
      assert.equal(formatReadinessDuration(view.durationMs), "未记录");
    }
  }
  assert.equal(formatReadinessDuration(0), "0ms");
});

test("missing metadata is explicit and overlong copy is safely bounded", () => {
  const longCopy = "x".repeat(500);
  const view = mapPlatformReadiness(response({
    checks: [{
      ...response().checks[0],
      owner: "",
      next_action: undefined,
      runbook: longCopy,
    }],
  }), NOW);
  assert.equal(view.state, "ready");
  assert.equal(view.checks[0].owner, "未记录");
  assert.equal(view.checks[0].nextAction, "未记录");
  assert.equal(view.checks[0].runbook.length, 180);
});

test("unsafe and unknown checks sort before degraded and ready evidence", () => {
  const checks = [
    { ...response().checks[0], id: "ready", status: "ready" },
    { ...response().checks[0], id: "degraded", status: "degraded" },
    { ...response().checks[0], id: "unsafe", status: "unsafe_to_serve" },
  ];
  const view = mapPlatformReadiness(response({ status: "unsafe_to_serve", checks }), NOW);
  assert.equal(view.state, "unsafe_to_serve");
  assert.deepEqual(view.checks.map((check) => check.id), ["unsafe", "degraded", "ready"]);
});
