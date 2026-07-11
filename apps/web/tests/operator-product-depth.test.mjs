import assert from "node:assert/strict";
import test from "node:test";
import {
  allowedCaseTransitions,
  caseMatchesFilter,
  caseOwnerLabel,
  caseSlaState,
  formatRecordedMetric,
  isFailedTraceStatus,
  operatorStatusLabel,
  traceStatusLabel,
  transitionLabel,
} from "../app/ops/_lib/operator.ts";

test("operator case state and actions follow backend truth", () => {
  const item = {
    id: "case-1",
    status: "unstaffed",
    ownership_status: "unassigned",
    allowed_transitions: ["assigned"],
  };
  assert.equal(operatorStatusLabel(item.status), "待接单");
  assert.equal(caseOwnerLabel(item), "尚未接单");
  assert.deepEqual(allowedCaseTransitions(item), ["assigned"]);
  assert.equal(transitionLabel(item.status, "assigned"), "接单");
  assert.deepEqual(
    allowedCaseTransitions({ ...item, ownership_status: "owned_by_other" }),
    [],
  );
});

test("operator filters and SLA expose urgent work without inventing state", () => {
  const now = new Date("2026-07-12T00:00:00Z");
  const item = {
    id: "case-urgent",
    summary: "疑似诈骗转账",
    status: "assigned",
    severity: "critical",
    ownership_status: "owned_by_me",
    household_id: "home-1",
    due_at: "2026-07-11T23:45:00Z",
  };
  assert.deepEqual(caseSlaState(item.due_at, now), {
    tone: "critical",
    label: "已超时 15 分钟",
    minutes: -15,
  });
  assert.equal(caseMatchesFilter(item, { query: "诈骗", status: "mine", severity: "critical" }, now), true);
  assert.equal(caseMatchesFilter(item, { query: "", status: "overdue", severity: "all" }, now), true);
  assert.equal(caseMatchesFilter(item, { query: "", status: "unstaffed", severity: "all" }, now), false);
});

test("trace completion and missing metrics stay truthful", () => {
  assert.equal(traceStatusLabel("completed"), "已完成");
  assert.equal(isFailedTraceStatus("completed"), false);
  assert.equal(isFailedTraceStatus("timeout"), true);
  assert.equal(formatRecordedMetric(undefined, "ms"), "未记录");
  assert.equal(formatRecordedMetric(0, "ms"), "0ms");
});
