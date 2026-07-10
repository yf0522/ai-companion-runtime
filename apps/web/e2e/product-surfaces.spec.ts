import { expect, test, type Page } from "@playwright/test";

type Role = "elder" | "family" | "operator";

function tokenFor(role: Role): string {
  const payload = Buffer.from(JSON.stringify({ sub: `test-${role}`, username: `${role}-review`, role })).toString("base64url");
  return `header.${payload}.signature`;
}

async function seedRole(page: Page, role: Role) {
  await page.addInitScript(({ seededRole, token }) => {
    localStorage.setItem("companion-auth", JSON.stringify({
      state: { hydrated: true, token, userId: `test-${seededRole}`, username: `${seededRole}-review`, role: seededRole },
      version: 0,
    }));
  }, { seededRole: role, token: tokenFor(role) });
}

async function json(page: Page, matcher: string | RegExp, body: unknown) {
  await page.route(matcher, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  }));
}

test("login keeps the real action in the first mobile viewport", async ({ page }, testInfo) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "进入照护空间" })).toBeVisible();
  await page.getByLabel("用户名").pressSequentially("elder-review");
  await page.getByLabel("密码").pressSequentially("companion-test-password");
  await expect(page.getByRole("button", { name: "安全登录" })).toBeEnabled();
  if (testInfo.project.name === "mobile") {
    const box = await page.getByRole("button", { name: "安全登录" }).boundingBox();
    expect(box?.y).toBeLessThan(844);
  }
});

test("elder companion presents status, next action, safety entry, and all mobile routes", async ({ page }, testInfo) => {
  await seedRole(page, "elder");
  await page.goto("/elder/companion");
  await expect(page.getByText("现在想先处理哪件事？")).toBeVisible();
  await expect(page.getByText("帮我判断是否诈骗")).toBeVisible();
  await expect(page.getByLabel("输入给陪伴助手的消息")).toBeVisible();
  if (testInfo.project.name === "mobile") {
    const nav = page.getByRole("navigation", { name: "长者移动导航" });
    await expect(nav.getByText("陪伴", { exact: true })).toBeVisible();
    await expect(nav.getByText("今日事项", { exact: true })).toBeVisible();
    await expect(nav.getByText("帮助", { exact: true })).toBeVisible();
  }
});

test("family overview prioritizes exceptions before due work", async ({ page }) => {
  await seedRole(page, "family");
  await json(page, "**/api/care-tasks", [{
    id: "task-1", title: "晚间降压药", status: "scheduled", next_fire_at: "2026-07-10T20:00:00Z", schedule_type: "daily", created_by: "family", version: 1,
  }]);
  await json(page, "**/api/notifications", {
    user_id: "elder-1", total: 1, status: "persisted", items: [{
      id: "alert-1", user_id: "elder-1", category: "scam_alert", title: "疑似转账诈骗", message: "对方要求立即转账并索取验证码。", trace_id: "trace-1", severity: "high", status: "delivered", created_at: "2026-07-10T08:00:00Z",
    }],
  });
  await page.goto("/family/overview");
  await expect(page.getByText("疑似转账诈骗")).toBeVisible();
  await expect(page.getByText("晚间降压药")).toBeVisible();
  const alertY = (await page.getByText("疑似转账诈骗").boundingBox())?.y || 0;
  const taskY = (await page.getByText("晚间降压药").boundingBox())?.y || 0;
  expect(alertY).toBeLessThan(taskY);
});

test("operator queue exposes severity, owner, next action, and evidence handles", async ({ page }) => {
  await seedRole(page, "operator");
  await json(page, "**/api/operator/cases", { total: 1, items: [{
    id: "case-1", user_id: "elder-1", safety_decision_id: "decision-12345678", notification_outbox_id: "outbox-12345678", status: "open", severity: "critical", owner_id: null, summary: "高风险诈骗，需要人工确认", resolution: null, due_at: "2026-07-10T09:00:00Z", created_at: "2026-07-10T08:00:00Z", resolved_at: null, state_version: 1,
  }] });
  await page.goto("/ops/care");
  await expect(page.getByText("高风险诈骗，需要人工确认")).toBeVisible();
  await expect(page.getByText("未分配")).toBeVisible();
  await expect(page.getByText(/decision decision/)).toBeVisible();
  await expect(page.getByText(/outbox outbox/)).toBeVisible();
  await expect(page.getByRole("link", { name: "查看案件" })).toBeVisible();
});

test("family mobile navigation keeps every route reachable", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile navigation contract");
  await seedRole(page, "family");
  await json(page, "**/api/care-tasks", []);
  await json(page, "**/api/notifications", { user_id: "elder-1", total: 0, status: "persisted", items: [] });
  await page.goto("/family/overview");
  const nav = page.getByRole("navigation", { name: "家属移动导航" });
  for (const label of ["概览", "照护任务", "告警", "人员权限", "联系人", "就绪检查", "摘要"]) {
    await expect(nav.getByText(label, { exact: true })).toBeAttached();
  }
});
