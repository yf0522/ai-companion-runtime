import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

function source(path) {
  return fs.readFileSync(new URL(path, import.meta.url), "utf8");
}

test("family task state follows the canonical backend matrix", () => {
  const taskState = source("../app/family/_lib/care-task.ts");
  const overview = source("../app/family/overview/page.tsx");
  const tasks = source("../app/family/tasks/page.tsx");
  for (const status of ["pending", "due", "done", "snoozed", "missed", "cancelled"]) {
    assert.match(taskState, new RegExp(`\\b${status}\\b`));
  }
  assert.match(taskState, /terminalStatuses.*done.*missed.*cancelled/s);
  assert.match(taskState, /scheduleType === "weekly"/);
  assert.match(taskState, /if \(due <= now\) due\.setDate\(due\.getDate\(\) \+ 1\)/);
  assert.match(overview, /fetchCareTasks\(\{ scope: "all", limit: 50 \}\)/);
  assert.match(overview, /fetchCareTasks\(\{ statuses: \["missed"\], scope: "all", limit: 1 \}\)/);
  assert.match(tasks, /statuses: \["done", "missed", "cancelled"\]/);
  assert.match(tasks, /\["pending", "due", "snoozed"\]\.includes\(status\)/);
});

test("family alerts never synthesize a delivery timeline", () => {
  const alertCard = source("../app/family/_components/FamilyAlertCard.tsx");
  assert.doesNotMatch(alertCard, /statusSteps|风险已记录.*已送达家人.*已确认处理/s);
  assert.match(alertCard, /delivery_events \|\| item\.receipts \|\| item\.events/);
  assert.match(alertCard, /return \[\.\.\.events\]\.sort/);
  assert.match(alertCard, /leftTime - rightTime/);
  assert.match(alertCard, /暂无逐条投递回执/);
  assert.match(alertCard, /不会据此推断家人已经查看或处理/);
});

test("family people only permits the current binding to leave", () => {
  const people = source("../app/family/people/page.tsx");
  assert.doesNotMatch(people, /inviteCareCircleMember|发送邀请/);
  assert.match(people, /member\.user_id === currentUserId/);
  assert.match(people, /不能替长者邀请他人/);
});

test("family contacts separates verified endpoints from escalation policy", () => {
  const contacts = source("../app/family/contacts/page.tsx");
  const apiClient = source("../lib/api-client.ts");
  assert.match(contacts, /联系方式只证明可以尝试联系/);
  assert.match(contacts, /不等于升级策略顺序/);
  assert.match(contacts, /last_test_at/);
  assert.doesNotMatch(contacts, /manage_contacts/);
  assert.match(contacts, /manage_reminders/);
  assert.match(contacts, /item\.priority \?\? "未记录"/);
  assert.match(apiClient, /priority: source\.priority \|\| 1/);
  assert.doesNotMatch(apiClient, /priority: source\.escalation_order/);
});

test("family readiness and summary expose accountable product depth", () => {
  const readiness = source("../app/family/readiness/page.tsx");
  const summary = source("../app/family/summary/page.tsx");
  assert.match(readiness, /下一步负责人/);
  assert.match(readiness, /证据时间/);
  assert.match(readiness, /safeCheckCopy/);
  assert.match(summary, /"7d" \| "30d" \| "90d"/);
  assert.match(summary, /denominator/);
  assert.match(summary, /previous_completion_rate/);
  assert.match(summary, /不展示私人对话或长期记忆内容/);
});
