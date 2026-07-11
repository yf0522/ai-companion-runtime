import { expect, test, type Page, type Route } from "@playwright/test";

function operatorToken(): string {
  const payload = Buffer.from(JSON.stringify({ sub: "operator-1", username: "ops-review", role: "operator" })).toString("base64url");
  return `header.${payload}.signature`;
}

async function seedOperator(page: Page) {
  await page.addInitScript((token) => {
    localStorage.setItem("companion-auth", JSON.stringify({
      state: { hydrated: true, token, userId: "operator-1", username: "ops-review", role: "operator" },
      version: 0,
    }));
  }, operatorToken());
}

async function fulfill(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

function operatorCase(overrides: Record<string, unknown> = {}) {
  return {
    id: "case-1",
    user_id: "elder-1",
    elder_user_id: "elder-1",
    household_id: "home-1",
    safety_decision_id: "decision-1",
    notification_outbox_id: "outbox-1",
    trace_id: "trace-1",
    status: "unstaffed",
    severity: "critical",
    owner_id: null,
    ownership_status: "unassigned",
    allowed_transitions: ["assigned"],
    can_add_activity: false,
    summary: "疑似诈骗转账，需要人工确认",
    resolution: null,
    due_at: "2026-07-11T23:45:00Z",
    created_at: "2026-07-11T23:00:00Z",
    resolved_at: null,
    state_version: 1,
    evidence: {
      safety_decision: { id: "decision-1", trace_id: "trace-1", risk_category: "scam_alert", policy_version: "risk:v2", action: "notify_family", confidence: 0.92 },
      notification_delivery: { outbox_id: "outbox-1", state: "delivered", provider: "signed_webhook", channel: "sms", attempt_count: 1, last_error: null },
    },
    ...overrides,
  };
}

test("operator queue uses canonical unstaffed state, filters, and truthful SLA", async ({ page }) => {
  await seedOperator(page);
  await page.route("**/api/operator/cases", (route) => fulfill(route, {
    total: 2,
    items: [
      operatorCase(),
      operatorCase({ id: "case-2", summary: "高风险健康提醒", status: "assigned", severity: "high", owner_id: "operator-1", ownership_status: "owned_by_me", allowed_transitions: ["resolved", "closed"], can_add_activity: true, due_at: null }),
    ],
  }));
  await page.goto("/ops/care");
  await expect(page.getByText("疑似诈骗转账，需要人工确认")).toBeVisible();
  await expect(page.getByText("待接单", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/decision decision|outbox outbox/i)).toHaveCount(0);
  await page.getByLabel("搜索案件").fill("健康");
  await expect(page.getByText("高风险健康提醒")).toBeVisible();
  await expect(page.getByText("疑似诈骗转账，需要人工确认")).toHaveCount(0);
  await page.getByLabel("搜索案件").fill("");
  await page.getByLabel("视图").selectOption("unstaffed");
  await expect(page.getByText("疑似诈骗转账，需要人工确认")).toBeVisible();
  await expect(page.getByText("高风险健康提醒")).toHaveCount(0);
});

test("operator case renders only legal actions and requires a resolution", async ({ page }) => {
  await seedOperator(page);
  let current: Record<string, unknown> = operatorCase({
    status: "assigned",
    owner_id: "operator-1",
    ownership_status: "owned_by_me",
    allowed_transitions: ["resolved", "closed"],
    can_add_activity: true,
  });
  let transitionBody: Record<string, unknown> = {};
  await page.route(/\/api\/operator\/cases\/case-1$/, async (route) => {
    if (route.request().method() === "GET") return fulfill(route, current);
    return route.fallback();
  });
  await page.route("**/api/operator/cases/case-1/activities", (route) => fulfill(route, {
    total: 2,
    items: [
      { id: "activity-1", case_id: "case-1", actor_type: "system", actor_id: null, activity_type: "case_created", summary: "案件创建", created_at: "2026-07-11T23:00:00Z" },
      { id: "activity-2", case_id: "case-1", actor_type: "caregiver", actor_id: "family-1", activity_type: "notification_acknowledged", summary: "家属确认已接手", created_at: "2026-07-11T23:10:00Z" },
    ],
  }));
  await page.route("**/api/operator/cases/case-1/transition", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    transitionBody = body;
    current = { ...current, status: "resolved", resolution: body.resolution as string, allowed_transitions: ["open", "closed"], state_version: 2 };
    return fulfill(route, current);
  });
  await page.goto("/ops/care/case-1");
  await expect(page.getByText("家属确认处理", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "标记已解决" }).click();
  await expect(page.getByText("解决或关闭案件前必须记录处置结论。" )).toBeVisible();
  await page.getByLabel("处置结论（解决或关闭时必填）").fill("已联系家属并确认没有发生转账，后续由女儿陪同。" );
  await page.getByRole("button", { name: "标记已解决" }).click();
  await expect.poll(() => transitionBody.status).toBe("resolved");
  expect(transitionBody.resolution).toContain("没有发生转账");
});

test("operator readiness starts with household discovery and exposes accountable blockers", async ({ page }) => {
  await seedOperator(page);
  await page.route("**/api/households?*", (route) => fulfill(route, {
    scope: "operator_household_discovery",
    total: 1,
    items: [{ id: "home-1", name: "林阿姨家庭", elder_user_id: "elder-1", elder_name: "林阿姨", status: "active", updated_at: "2026-07-11T23:00:00Z" }],
  }));
  await page.route("**/api/households/home-1/readiness", (route) => fulfill(route, {
    household_id: "home-1",
    status: "blocked",
    updated_at: "2026-07-11T23:20:00Z",
    next_action: "发送一次真实测试通知并等待回执",
    checks: [
      { key: "verified_contact", label: "紧急联系方式已验证", status: "ready", detail: "一个联系方式已验证", required: true, owner: "家庭管理员", action: null, evidence: { verified_contact_count: 1 }, evidence_at: "2026-07-11T23:20:00Z" },
      { key: "production_provider_delivery_test", label: "通知通道已送达验证", status: "blocked", detail: "尚无真实送达回执", required: true, owner: "平台运营", action: "发送一次真实测试通知并等待回执", evidence: { confirmed_delivery_count: 0 }, evidence_at: "2026-07-11T23:20:00Z" },
    ],
  }));
  await page.goto("/ops/households/readiness");
  await expect(page.getByText("林阿姨家庭")).toBeVisible();
  await page.getByRole("button", { name: "查看就绪" }).click();
  await expect(page.getByText("通知通道已送达验证")).toBeVisible();
  await expect(page.getByText("平台运营", { exact: true })).toBeVisible();
  await expect(page.getByText("发送一次真实测试通知并等待回执", { exact: true }).first()).toBeVisible();
});

test("operator trace keeps unknown metrics unknown and links back to its audited case", async ({ page }) => {
  await seedOperator(page);
  await page.route(/\/api\/traces\?/, (route) => fulfill(route, {
    contract_version: "trace-list.v2",
    scope: "operator_case",
    total: 1,
    limit: 100,
    offset: 0,
    items: [{ trace_id: "trace-1", started_at: null, event_count: null, failed_event_count: null, status: "unknown", user_id: "elder-1", case_id: "case-1", case_ids: ["case-1"], case_status: "assigned", severity: "critical" }],
  }));
  await page.route("**/api/traces/trace-1", (route) => fulfill(route, {
    trace_id: "trace-1",
    user_id: "elder-1",
    session_id: null,
    started_at: null,
    total_latency_ms: null,
    events: [{ step_index: 1, step_name: "risk_detection", status: "completed", latency_ms: 0, output: { risk: "critical" } }],
    model_calls: [{ provider: "demo", model: "model-a", role: "primary", total_latency_ms: null, ttft_ms: 0, status: "completed" }],
    tool_calls: [],
    cost_summary: { total_tokens: null, total_cost_cents: null },
    authorization: { scope: "operator_case", case_id: "case-1", case_ids: ["case-1"], audited: true },
  }));
  await page.goto("/ops/traces");
  await expect(page.getByLabel("追踪列表").getByText("状态未记录", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "查看" }).click();
  await expect(page.getByRole("link", { name: /返回案件/ })).toBeVisible();
  await expect(page.getByText("未记录", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("0ms", { exact: true })).toBeVisible();
});
