import { expect, test, type Page, type Route } from "@playwright/test";

function familyToken(): string {
  const payload = Buffer.from(JSON.stringify({ sub: "test-family", username: "family-review", role: "family" })).toString("base64url");
  return `header.${payload}.signature`;
}

async function seedFamily(page: Page) {
  await page.addInitScript((token) => {
    localStorage.setItem("companion-auth", JSON.stringify({
      state: { hydrated: true, token, userId: "test-family", username: "family-review", role: "family" },
      version: 0,
    }));
  }, familyToken());
}

async function fulfill(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

test("tasks use canonical states, keep history, and create the next occurrence in the future", async ({ page }) => {
  await seedFamily(page);
  let createdDueAt = "";
  const tasks = [
    { id: "due", title: "现在测量血压", status: "due", due_at: "2026-07-11T01:00:00Z", schedule_type: "once", created_by: "family", version: 1 },
    { id: "missed", title: "已经错过的服药任务", status: "missed", due_at: "2026-07-10T01:00:00Z", schedule_type: "daily", created_by: "family", version: 1 },
    { id: "done", title: "已经完成的饮水任务", status: "done", due_at: "2026-07-09T01:00:00Z", schedule_type: "daily", created_by: "elder", version: 2 },
    { id: "cancelled", title: "已经停用的运动任务", status: "cancelled", due_at: "2026-07-08T01:00:00Z", schedule_type: "weekly", created_by: "family", version: 3 },
    { id: "snoozed", title: "延后的复诊提醒", status: "snoozed", due_at: "2026-07-12T01:00:00Z", schedule_type: "once", created_by: "family", version: 2 },
  ];
  await page.route("**/api/care-tasks**", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      createdDueAt = body.due_at;
      return fulfill(route, { id: "new-task", ...body, status: "pending", version: 1, _action: "caretask_create" });
    }
    return fulfill(route, { items: tasks, total: tasks.length });
  });

  await page.goto("/family/tasks");
  await expect(page.getByText("现在到期", { exact: true })).toBeVisible();
  await expect(page.getByText("已错过", { exact: true })).toBeVisible();
  await expect(page.locator('[aria-label="照护任务统计"]')).toContainText("进行中2");
  await page.getByRole("button", { name: "历史" }).click();
  await expect(page.getByText("已经完成的饮水任务")).toBeVisible();
  await expect(page.getByText("已经停用的运动任务")).toBeVisible();

  await page.getByRole("button", { name: "新增照护任务" }).click();
  await page.getByLabel("任务名称").fill("明天电话问候");
  await page.getByLabel("重复").selectOption("once");
  const tomorrow = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  await page.getByLabel("日期").fill(tomorrow);
  await page.getByLabel("时间").fill("09:30");
  await page.getByRole("button", { name: "保存照护任务" }).click();
  await expect.poll(() => createdDueAt).not.toBe("");
  expect(new Date(createdDueAt).getTime()).toBeGreaterThan(Date.now());
});

test("alerts show only real receipt events and call unknown evidence unknown", async ({ page }) => {
  await seedFamily(page);
  await page.route("**/api/notifications", (route) => fulfill(route, {
    status: "persisted", total: 2, user_id: "elder-1", items: [
      { id: "open", user_id: "elder-1", category: "scam_alert", title: "转账风险", message: "需要确认是否已联系本人。", trace_id: null, severity: "high", status: "delivered", created_at: "2026-07-11T08:00:00Z" },
      { id: "ack", user_id: "elder-1", category: "emotional_low", title: "关怀提醒", message: "已经由家属接手。", trace_id: null, severity: "medium", status: "acknowledged", acknowledged_at: "2026-07-11T09:10:00Z", acknowledged_by_name: "小林", created_at: "2026-07-11T07:00:00Z", delivery_events: [
        { id: "receipt-2", event_type: "delivered", actor_name: "短信服务", occurred_at: "2026-07-11T07:02:00Z" },
        { id: "receipt-1", event_type: "accepted", actor_name: "短信服务", occurred_at: "2026-07-11T07:01:00Z" },
      ] },
    ],
  }));
  await page.goto("/family/alerts");
  await expect(page.getByText("暂无逐条投递回执")).toBeVisible();
  await expect(page.getByText("不会据此推断家人已经查看或处理", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "已确认 1" }).click();
  await expect(page.getByText("服务已接受", { exact: true })).toBeVisible();
  await expect(page.getByText("已送达", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "真实投递与确认记录" }).locator("strong")).toHaveText(["服务已接受", "已送达"]);
  await expect(page.getByText(/小林/)).toBeVisible();
});

test("people renders consent and permissions but only the current binding can leave", async ({ page }) => {
  await seedFamily(page);
  await page.route("**/api/care-circle", (route) => fulfill(route, {
    household_id: "house-1", permissions: [], invites: [{ email: "pending@example.com", role: "caregiver", status: "pending", expires_at: "2026-07-20T00:00:00Z" }], members: [
      { id: "elder", user_id: "elder-1", name: "林阿姨", role: "elder", status: "active", consent_status: "owner", permissions: [] },
      { id: "self", user_id: "test-family", binding_id: "binding-self", name: "小林", relationship: "女儿", role: "primary_caregiver", status: "active", consent_status: "active", permissions: ["view_notifications", "manage_reminders"] },
      { id: "other", user_id: "other-family", binding_id: "binding-other", name: "小周", relationship: "邻居", role: "caregiver", status: "active", consent_status: "active", permissions: ["view_notifications"] },
    ],
  }));
  await page.goto("/family/people");
  await expect(page.getByText("女儿", { exact: true })).toBeVisible();
  await expect(page.getByText("查看通知结果", { exact: true })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "退出照护圈" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: /邀请/ })).toHaveCount(0);
  await expect(page.getByText("pending@example.com")).toBeVisible();
});

test("contacts distinguishes endpoint verification from escalation policy", async ({ page }) => {
  await seedFamily(page);
  await page.route("**/api/contacts", (route) => fulfill(route, { items: [{
    id: "contact-1", name: "女儿小林", channel: "phone", value: "13800000000", verification_status: "verified", verification_state: "verified", priority: 1, escalation_order: null, available: true, availability: { label: "每天 08:00–22:00" }, last_verified_at: "2026-07-10T08:00:00Z",
  }], total: 1 }));
  await page.route("**/api/care-circle", (route) => fulfill(route, { household_id: "house-1", permissions: [], invites: [], members: [{ id: "self", user_id: "test-family", name: "小林", role: "caregiver", status: "active", permissions: ["manage_reminders"] }] }));
  await page.route("**/api/households/readiness", (route) => fulfill(route, { household_id: "house-1", status: "not_ready", updated_at: "2026-07-11T08:00:00Z", next_action: null, checks: [{ key: "active_escalation_policy", label: "raw", detail: "raw", status: "missing", required: true }] }));
  await page.goto("/family/contacts");
  await expect(page.getByText("联系端点", { exact: true })).toBeVisible();
  await expect(page.getByText("每天 08:00–22:00", { exact: true })).toBeVisible();
  await expect(page.getByText(/不等于升级策略顺序/)).toBeVisible();
  await expect(page.getByText("最近投递测试", { exact: true })).toBeVisible();
  await expect(page.getByText("尚未检测到可用的升级策略", { exact: false })).toBeVisible();
});

test("readiness translates internal checks into owner, action, and evidence", async ({ page }) => {
  await seedFamily(page);
  await page.route("**/api/households/readiness", (route) => fulfill(route, {
    household_id: "house-1", status: "not_ready", updated_at: "2026-07-11T08:00:00Z", next_action: "Complete: Production provider delivery test", checks: [
      { key: "verified_contact", label: "Verified contact", detail: "Raw internal detail", status: "ready", required: true },
      { key: "production_provider_delivery_test", label: "Production provider delivery test", detail: "Complete provider wiring", status: "missing", required: true },
    ],
  }));
  await page.goto("/family/readiness");
  await expect(page.getByText("通知投递已经实测", { exact: true })).toBeVisible();
  await expect(page.getByText("下一步负责人", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("证据时间", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Production provider|Raw internal|Complete provider/i)).toHaveCount(0);
});

test("summary has an explicit range, denominator, trend, and outliers", async ({ page }) => {
  await seedFamily(page);
  await page.route("**/api/memory/family-summary**", (route) => fulfill(route, {
    elder_user_id: "elder-1", family_user_id: "test-family", summary: {
      summary_type: "care_outcomes_only", total_outcomes: 4, denominator: 4, completion_rate: 0.75, previous_completion_rate: 0.5,
      range_start: "2026-07-05T00:00:00Z", range_end: "2026-07-11T23:59:59Z", by_status: { done: 3, missed: 1 }, items: [
        { task_id: "done", title: "晚间服药", task_type: "medication", status: "done", due_at: "2026-07-10T12:00:00Z", completed_at: "2026-07-10T12:05:00Z", owner_name: "林阿姨" },
        { task_id: "missed", title: "午后散步", task_type: "exercise", status: "missed", due_at: "2026-07-09T08:00:00Z", completed_at: null, owner_name: "小林" },
      ],
    },
  }));
  await page.goto("/family/summary");
  await expect(page.getByText("75%", { exact: true })).toBeVisible();
  await expect(page.getByText("3 / 4 项有结果的任务", { exact: true })).toBeVisible();
  await expect(page.getByText("+25 个百分点", { exact: true })).toBeVisible();
  await expect(page.getByText("午后散步").first()).toBeVisible();
  await page.getByRole("button", { name: "最近 30 天" }).click();
  await expect(page.getByRole("heading", { name: "最近 30 天发生了什么" })).toBeVisible();
});

test("mobile tasks show the attention item before the creation form", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile hierarchy contract");
  await seedFamily(page);
  await page.route("**/api/care-tasks**", (route) => fulfill(route, { items: [{ id: "missed", title: "今天错过的任务", status: "missed", due_at: "2026-07-11T01:00:00Z", schedule_type: "once", created_by: "family", version: 1 }], total: 1 }));
  await page.goto("/family/tasks");
  const item = page.getByText("今天错过的任务", { exact: true });
  await expect(item).toBeVisible();
  const box = await item.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
  await expect(page.getByLabel("新增照护任务")).toHaveCount(0);
});
