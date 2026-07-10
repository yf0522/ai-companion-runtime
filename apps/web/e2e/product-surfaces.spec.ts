import { expect, test, type Locator, type Page } from "@playwright/test";

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

async function failingJson(page: Page, matcher: string | RegExp) {
  await page.route(matcher, (route) => route.fulfill({
    status: 500,
    contentType: "application/json",
    body: JSON.stringify({ detail: "test failure" }),
  }));
}

async function visibleBox(locator: Locator) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

test("login keeps the real action in the first mobile viewport", async ({ page }, testInfo) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "进入照护空间" })).toBeVisible();
  await page.getByLabel("用户名").pressSequentially("elder-review");
  await page.getByLabel("密码").pressSequentially("companion-test-password");
  await expect(page.getByRole("button", { name: "安全登录" })).toBeEnabled();
  if (testInfo.project.name === "mobile") {
    const box = await visibleBox(page.getByRole("button", { name: "安全登录" }));
    expect(box.y + box.height).toBeLessThanOrEqual(844);
  }
});

test("elder companion presents status, next action, safety entry, and all mobile routes", async ({ page }, testInfo) => {
  await seedRole(page, "elder");
  await page.goto("/elder/companion");
  await expect(page.getByText("今天想先说哪件事？")).toBeVisible();
  await expect(page.getByText("帮我判断是否诈骗")).toBeVisible();
  await expect(page.getByLabel("输入给陪伴助手的消息")).toBeVisible();
  await expect(page.getByText(/Harness|Trace|runtime|outbox|权限隔离/i)).toHaveCount(0);
  const helpBox = await visibleBox(page.getByRole("link", { name: "现在需要帮助？先联系家人" }));
  expect(helpBox.height).toBeGreaterThanOrEqual(44);
  const modeBox = await visibleBox(page.getByLabel("选择回应方式"));
  expect(modeBox.height).toBeGreaterThanOrEqual(44);
  await page.getByLabel("选择回应方式").click();
  const runtimeSelector = page.getByRole("radiogroup", { name: "回应方式" });
  await expect(runtimeSelector.getByRole("radio", { name: "标准模式" })).toBeVisible();
  await expect(runtimeSelector.getByRole("radio", { name: "实验模式" })).toBeVisible();
  await runtimeSelector.getByRole("radio", { name: "实验模式" }).click();
  await expect(runtimeSelector.getByRole("radio", { name: "实验模式" })).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("companion.agent_runtime"))).toBe("pi_experimental");
  if (testInfo.project.name === "mobile") {
    const nav = page.getByRole("navigation", { name: "长者移动导航" });
    await expect(nav.getByText("陪伴", { exact: true })).toBeVisible();
    await expect(nav.getByText("今日事项", { exact: true })).toBeVisible();
    await expect(nav.getByText("帮助", { exact: true })).toBeVisible();
    const composerBox = await visibleBox(page.locator(".astryx-chat-composer"));
    const navBox = await visibleBox(nav);
    expect(composerBox.height).toBeGreaterThanOrEqual(80);
    expect(composerBox.y + composerBox.height).toBeLessThanOrEqual(navBox.y);
  }
});

test("family overview prioritizes exceptions before due work", async ({ page }) => {
  await seedRole(page, "family");
  await json(page, "**/api/care-tasks", [
    { id: "task-1", title: "晚间降压药", status: "scheduled", next_fire_at: "2026-07-10T20:00:00Z", schedule_type: "daily", created_by: "family", version: 1 },
    { id: "task-2", title: "测量血压", status: "active", next_fire_at: "2026-07-11T08:00:00Z", schedule_type: "daily", created_by: "family", version: 1 },
    { id: "task-3", title: "午间问候", status: "scheduled", next_fire_at: "2026-07-11T12:00:00Z", schedule_type: "daily", created_by: "family", version: 1 },
    { id: "task-4", title: "复诊提醒", status: "scheduled", next_fire_at: "2026-07-12T09:00:00Z", schedule_type: "once", created_by: "family", version: 1 },
    { id: "task-5", title: "已停用提醒", status: "scheduled", is_active: false, next_fire_at: "2026-07-12T12:00:00Z", schedule_type: "once", created_by: "family", version: 1 },
  ]);
  await json(page, "**/api/notifications", {
    user_id: "elder-1", total: 1, status: "persisted", items: [{
      id: "alert-1", user_id: "elder-1", category: "scam_alert", title: "疑似转账诈骗", message: "对方要求立即转账并索取验证码。", trace_id: "trace-1", severity: "high", status: "delivered", created_at: "2026-07-10T08:00:00Z",
    }],
  });
  await page.goto("/family/overview");
  await expect(page.getByText("疑似转账诈骗")).toBeVisible();
  await expect(page.getByText("晚间降压药")).toBeVisible();
  await expect(page.getByText(/FAMILY CARE PULSE|NEEDS ATTENTION|CARE RHYTHM|权限隔离/i)).toHaveCount(0);
  const alertBox = await visibleBox(page.getByText("疑似转账诈骗"));
  const taskBox = await visibleBox(page.getByText("晚间降压药"));
  expect(alertBox.y).toBeLessThan(taskBox.y);
  await expect(page.getByRole("region", { name: "当前照护状态" })).toContainText("4 项照护安排正在进行");
  if (page.viewportSize()?.width === 390) {
    const primaryActionBox = await visibleBox(page.getByRole("link", { name: "查看并处理" }));
    const secondaryActionBox = await visibleBox(page.getByRole("link", { name: "联系本人" }));
    const taskLinkBox = await visibleBox(page.getByRole("link", { name: "查看晚间降压药" }));
    expect(primaryActionBox.height).toBeGreaterThanOrEqual(44);
    expect(secondaryActionBox.height).toBeGreaterThanOrEqual(44);
    expect(taskLinkBox.height).toBeGreaterThanOrEqual(44);
    expect(primaryActionBox.y + primaryActionBox.height).toBeLessThanOrEqual(844);
  }
});

test("family overview never presents an unavailable notification state as all clear", async ({ page }) => {
  await seedRole(page, "family");
  await json(page, "**/api/care-tasks", [{
    id: "task-1", title: "晚间降压药", status: "scheduled", next_fire_at: "2026-07-10T20:00:00Z", schedule_type: "daily", created_by: "family", version: 1,
  }]);
  await json(page, "**/api/notifications", { user_id: "elder-1", total: 0, status: "unavailable", items: [] });
  await page.goto("/family/overview");
  await expect(page.getByRole("heading", { name: "暂时无法确认是否有新的异常" })).toBeVisible();
  await expect(page.getByText("晚间降压药")).toBeVisible();
  await expect(page.getByText("今天的照护安排都在正常进行", { exact: true })).toHaveCount(0);
  await expect(page.getByText("目前没有需要处理的异常", { exact: true })).toHaveCount(0);
  await expect(page.getByText("0 件事情需要关注", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "当前照护状态" })).toContainText("告警状态暂时不可用");
});

test("featured alert surface treatment follows severity", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "computed-style contract");
  await seedRole(page, "family");
  await json(page, "**/api/care-tasks", []);
  let severity = "medium";
  await page.route("**/api/notifications", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      user_id: "elder-1",
      total: 1,
      status: "persisted",
      items: [{ id: "alert-1", user_id: "elder-1", category: "emotional_low", title: "需要关注", message: "请查看当前情况。", trace_id: "trace-1", severity, status: "delivered", created_at: "2026-07-10T08:00:00Z" }],
    }),
  }));

  const surfaceSignature = () => page.locator(".attention-card").evaluate((element) => {
    const card = getComputedStyle(element);
    const icon = getComputedStyle(element.querySelector(".attention-card-icon") as Element);
    return [card.backgroundColor, card.borderLeftColor, icon.backgroundColor].join("|");
  });

  await page.goto("/family/overview");
  const mediumSignature = await surfaceSignature();
  severity = "low";
  await page.reload();
  const lowSignature = await surfaceSignature();
  severity = "high";
  await page.reload();
  const highSignature = await surfaceSignature();

  expect(new Set([highSignature, mediumSignature, lowSignature]).size).toBe(3);
  expect(highSignature).toContain("rgb(166, 77, 64)");
  expect(mediumSignature).toContain("rgb(154, 103, 45)");
  expect(lowSignature).toContain("rgb(82, 110, 119)");
});

test("unknown family alert severity is conservative and outranks low", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "unknown-severity contract");
  await seedRole(page, "family");
  await json(page, "**/api/care-tasks", []);
  await json(page, "**/api/notifications", {
    user_id: "elder-1",
    total: 2,
    status: "persisted",
    items: [
      { id: "alert-low", user_id: "elder-1", category: "none", title: "低风险提醒", message: "稍后查看。", trace_id: "trace-low", severity: "low", status: "delivered", created_at: "2026-07-10T08:00:00Z" },
      { id: "alert-unknown", user_id: "elder-1", category: "none", title: "风险等级待确认", message: "请先确认风险等级。", trace_id: "trace-unknown", severity: "unexpected", status: "delivered", created_at: "2026-07-10T09:00:00Z" },
    ],
  });
  await page.goto("/family/overview");
  await expect(page.locator(".attention-card h3")).toHaveText("风险等级待确认");
  const borderColor = await page.locator(".attention-card").evaluate((element) => getComputedStyle(element).borderLeftColor);
  expect(borderColor).toBe("rgb(154, 103, 45)");
});

test("family mobile alert history keeps each delivery state visible", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile alert-state contract");
  await seedRole(page, "family");
  await json(page, "**/api/notifications", {
    user_id: "elder-1",
    total: 2,
    status: "persisted",
    items: [
      { id: "alert-delivered", user_id: "elder-1", category: "scam_alert", title: "转账风险", message: "通知已送达家人。", trace_id: "trace-1", severity: "high", status: "delivered", created_at: "2026-07-10T08:00:00Z" },
      { id: "alert-acknowledged", user_id: "elder-1", category: "emotional_low", title: "情绪关怀", message: "家人已确认处理。", trace_id: "trace-2", severity: "medium", status: "acknowledged", created_at: "2026-07-09T08:00:00Z" },
    ],
  });
  await page.goto("/family/alerts");
  await expect(page.getByText("已送达", { exact: true })).toBeVisible();
  await expect(page.getByText("已确认", { exact: true })).toBeVisible();
  await expect(page.getByText("展示风险事件、通知状态和处理动作；未确认的投递不会写成已通知。", { exact: true })).toHaveCount(0);
});

test("family alert history never labels an unavailable state as empty", async ({ page }) => {
  await seedRole(page, "family");
  await json(page, "**/api/notifications", { user_id: "elder-1", total: 0, status: "unavailable", items: [] });
  await page.goto("/family/alerts");
  await expect(page.getByText("通知服务暂时不可用", { exact: true })).toBeVisible();
  await expect(page.getByText("暂无告警", { exact: true })).toHaveCount(0);
});

test("family alert read failure never presents zero counts", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "failed-read contract");
  await seedRole(page, "family");
  await failingJson(page, "**/api/notifications");
  await page.goto("/family/alerts");
  await expect(page.getByRole("main", { name: "告警" }).getByRole("alert")).toBeVisible();
  await expect(page.locator('[aria-label="告警统计"]')).toHaveCount(0);
  await expect(page.getByText("暂无告警", { exact: true })).toHaveCount(0);
});

test("family task metrics and labels respect explicit disabled state", async ({ page }) => {
  await seedRole(page, "family");
  await json(page, "**/api/care-tasks", [
    { id: "task-active", title: "服药提醒", status: "scheduled", is_active: true, next_fire_at: "2026-07-10T20:00:00Z", schedule_type: "daily", created_by: "family", version: 1 },
    { id: "task-disabled", title: "已停用提醒", status: "scheduled", is_active: false, next_fire_at: "2026-07-10T21:00:00Z", schedule_type: "daily", created_by: "family", version: 1 },
    { id: "task-completed", title: "已完成提醒", status: "completed", is_active: true, next_fire_at: "2026-07-10T19:00:00Z", schedule_type: "daily", created_by: "family", version: 1 },
  ]);
  await page.goto("/family/tasks");
  await expect(page.locator('[aria-label="照护任务统计"]')).toContainText("进行中1");
  await expect(page.getByText("已停用", { exact: true })).toBeVisible();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
});

test("family task read failure never presents zero counts", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "failed-read contract");
  await seedRole(page, "family");
  await failingJson(page, "**/api/care-tasks");
  await page.goto("/family/tasks");
  await expect(page.getByRole("main", { name: "照护任务" }).getByRole("alert")).toBeVisible();
  await expect(page.locator('[aria-label="照护任务统计"]')).toHaveCount(0);
  await expect(page.getByText("还没有照护任务", { exact: true })).toHaveCount(0);
});

test("secondary family read failures never present zero or empty claims", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "failed-read contract");
  await seedRole(page, "family");

  await failingJson(page, "**/api/care-circle");
  await page.goto("/family/people");
  await expect(page.getByRole("main", { name: "人员与权限" }).getByRole("alert")).toBeVisible();
  await expect(page.locator('[aria-label="照护圈统计"]')).toHaveCount(0);
  await expect(page.getByText("还没有照护圈成员", { exact: true })).toHaveCount(0);

  await failingJson(page, "**/api/contacts");
  await page.goto("/family/contacts");
  await expect(page.getByRole("main", { name: "已验证联系人" }).getByRole("alert")).toBeVisible();
  await expect(page.locator('[aria-label="联系人统计"]')).toHaveCount(0);
  await expect(page.getByText("还没有联系人", { exact: true })).toHaveCount(0);

  await failingJson(page, "**/api/households/readiness");
  await page.goto("/family/readiness");
  await expect(page.getByRole("main", { name: "家庭就绪检查" }).getByRole("alert")).toBeVisible();
  await expect(page.getByText("暂无就绪数据", { exact: true })).toHaveCount(0);
});

test("elder task read failure never presents an all-clear claim", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "failed-read contract");
  await seedRole(page, "elder");
  await failingJson(page, "**/api/care-tasks");
  await page.goto("/elder/today");
  await expect(page.getByRole("heading", { name: "暂时无法确认今日事项" })).toBeVisible();
  await expect(page.getByRole("main", { name: "今日事项" }).getByRole("alert")).toBeVisible();
  await expect(page.getByText("当前没有待确认事项", { exact: true })).toHaveCount(0);
  await expect(page.getByText("今天没有待确认事项", { exact: true })).toHaveCount(0);
});

test("elder navigation remains reachable at the tablet release width", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "tablet navigation contract");
  await page.setViewportSize({ width: 768, height: 1024 });
  await seedRole(page, "elder");
  await page.goto("/elder/companion");
  const nav = page.getByRole("navigation", { name: "长者移动导航" });
  await expect(nav).toBeVisible();
  for (const label of ["陪伴", "今日事项", "帮助"]) {
    await expect(nav.getByText(label, { exact: true })).toBeVisible();
  }
  const composerBox = await visibleBox(page.locator(".astryx-chat-composer"));
  const navBox = await visibleBox(nav);
  expect(composerBox.y + composerBox.height).toBeLessThanOrEqual(navBox.y);
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

test("unknown operator severity never renders as success", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "unknown-severity contract");
  await seedRole(page, "operator");
  await json(page, "**/api/operator/cases", { total: 1, items: [{
    id: "case-unknown", user_id: "elder-1", safety_decision_id: null, notification_outbox_id: null, status: "open", severity: "unexpected", owner_id: null, summary: "风险等级待确认", resolution: null, due_at: null, created_at: "2026-07-10T08:00:00Z", resolved_at: null, state_version: 1,
  }] });
  await page.goto("/ops/care");
  const badge = page.getByText("风险待确认", { exact: true });
  await expect(badge).toBeVisible();
  const colors = await badge.evaluate((element) => {
    const probe = document.createElement("span");
    probe.style.backgroundColor = "var(--color-success)";
    document.body.appendChild(probe);
    const result = {
      badge: getComputedStyle(element).backgroundColor,
      success: getComputedStyle(probe).backgroundColor,
    };
    probe.remove();
    return result;
  });
  expect(colors.badge).not.toBe(colors.success);
});

test("operator read failure never presents zero case counts", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "failed-read contract");
  await seedRole(page, "operator");
  await failingJson(page, "**/api/operator/cases");
  await page.goto("/ops/care");
  await expect(page.getByRole("main", { name: "照护运营" }).getByRole("alert")).toBeVisible();
  await expect(page.locator('[aria-label="运营案件状态"]')).toHaveCount(0);
  await expect(page.getByText("暂无待处理案件", { exact: true })).toHaveCount(0);
});

test("operator trace read failure never presents a zero queue", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "failed-read contract");
  await seedRole(page, "operator");
  await failingJson(page, /\/api\/traces\?/);
  await page.goto("/ops/traces");
  await expect(page.getByRole("main", { name: "追踪" }).getByRole("alert")).toBeVisible();
  await expect(page.getByText("0 条最近链路", { exact: true })).toHaveCount(0);
  await expect(page.getByText("暂无追踪记录", { exact: true })).toHaveCount(0);
});

test("family mobile navigation keeps every route reachable", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile navigation contract");
  await seedRole(page, "family");
  await json(page, "**/api/care-tasks", []);
  await json(page, "**/api/notifications", { user_id: "elder-1", total: 0, status: "persisted", items: [] });
  await page.goto("/family/overview");
  const nav = page.getByRole("navigation", { name: "家属移动导航" });
  await expect(nav.locator("a")).toHaveCount(4);
  for (const label of ["概览", "任务", "告警", "家人"]) {
    await expect(nav.getByText(label, { exact: true })).toBeVisible();
  }
  const navOverflow = await nav.evaluate((element) => element.scrollWidth - element.clientWidth);
  expect(navOverflow).toBeLessThanOrEqual(1);

  await page.getByLabel("打开全部功能").click();
  for (const label of ["概览", "照护任务", "告警", "人员权限", "联系人", "就绪检查", "摘要"]) {
    await expect(page.locator(".consumer-menu-panel").getByText(label, { exact: true })).toBeVisible();
  }
});
