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

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function readiness(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "operator-platform-readiness.v1",
    scope: "platform",
    status: "ready",
    checked_at: new Date().toISOString(),
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
        observed: {
          mode: "native",
          queue_depth: 0,
          heads: ["20260712_add_platform_readiness", "20260711_add_memory_receipts"],
        },
      },
      {
        id: "worker",
        label: "Background worker",
        status: "ready",
        summary: "worker heartbeat observed",
        duration_ms: 2.1,
        owner: "Runtime operations",
        next_action: "Inspect worker heartbeat and queue consumption.",
        runbook: "platform-readiness#worker",
      },
    ],
    ...overrides,
  };
}

test.beforeEach(async ({ page }) => {
  await seedOperator(page);
});

test("renders fresh ready, degraded, and unsafe evidence without losing repair ownership", async ({ page }, testInfo) => {
  let fixture = readiness();
  await page.route("**/api/operator/platform/readiness", (route) => fulfill(route, fixture));

  await page.goto("/ops/platform");
  await expect(page.getByRole("status", { name: "平台结论：可承载服务" })).toBeVisible();
  await expect(page.getByText("平台可以承载服务", { exact: true })).toBeVisible();
  await expect(page.getByText("Platform runtime", { exact: true })).toBeVisible();
  await expect(page.getByText("Verify the active Redis URL and authentication profile.", { exact: true })).toBeVisible();
  await expect(page.getByText("0", { exact: true })).toBeVisible();
  await expect(page.getByText("20260712_add_platform_readiness · 20260711_add_memory_receipts", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("platform-ready.png"), fullPage: true });

  fixture = readiness({
    status: "degraded",
    checks: [
      { ...readiness().checks[0], status: "degraded", summary: "redis is available without persistence" },
      readiness().checks[1],
    ],
  });
  await page.reload();
  await expect(page.getByText("平台可用，但能力受限", { exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "平台结论：能力受限" })).toHaveAttribute("data-readiness-state", "degraded");
  await expect(page.getByText("平台可以承载服务", { exact: true })).toHaveCount(0);

  fixture = readiness({
    status: "unsafe_to_serve",
    checks: [
      readiness().checks[0],
      { ...readiness().checks[1], status: "unsafe_to_serve", summary: "worker heartbeat is missing" },
    ],
  });
  await page.reload();
  await expect(page.getByText("平台不可承载服务", { exact: true })).toBeVisible();
  await expect(page.getByText("Background worker", { exact: true })).toBeVisible();
  await expect(page.getByText("阻止服务", { exact: true })).toBeVisible();
});

test("stale and malformed evidence never render a healthy verdict", async ({ page }) => {
  let fixture = readiness({ checked_at: new Date(Date.now() - 120_000).toISOString() });
  await page.route("**/api/operator/platform/readiness", (route) => fulfill(route, fixture));

  await page.goto("/ops/platform");
  await expect(page.getByText("就绪证据已过期", { exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "平台结论：证据已过期" })).toHaveAttribute("data-readiness-state", "stale");
  await expect(page.getByText("平台可以承载服务", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "刷新平台就绪证据" })).toBeEnabled();

  fixture = readiness({
    status: "ready",
    checked_at: undefined,
    duration_ms: undefined,
    checks: [{ ...readiness().checks[0], status: "mystery" }],
  });
  await page.reload();
  await expect(page.getByText("平台状态待确认", { exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "平台结论：状态待确认" })).toHaveAttribute("data-readiness-state", "unknown");
  await expect(page.getByText("未记录", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/状态待确认/).last()).toBeVisible();
  await expect(page.getByText("平台可以承载服务", { exact: true })).toHaveCount(0);
});

test("manual refresh replaces the previous evidence and announces the new verdict", async ({ page }) => {
  let requestCount = 0;
  await page.route("**/api/operator/platform/readiness", (route) => {
    requestCount += 1;
    const body = requestCount === 1
      ? readiness({ checked_at: "2026-01-01T00:00:00Z" })
      : readiness({
        status: "unsafe_to_serve",
        checks: [{ ...readiness().checks[0], status: "unsafe_to_serve" }],
      });
    return fulfill(route, body);
  });

  await page.goto("/ops/platform");
  await expect(page.getByText("就绪证据已过期", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "刷新平台就绪证据" }).click();
  await expect(page.getByText("平台不可承载服务", { exact: true })).toBeVisible();
  await expect.poll(() => requestCount).toBe(2);
});

test("401 returns to login while 403 and network failures show no summary metrics", async ({ page }) => {
  let mode: "unauthorized" | "forbidden" | "network" = "unauthorized";
  await page.route("**/api/operator/platform/readiness", async (route) => {
    if (mode === "unauthorized") return fulfill(route, { detail: "Not authenticated" }, 401);
    if (mode === "forbidden") return fulfill(route, { detail: "Operator role required" }, 403);
    return route.abort("failed");
  });

  await page.goto("/ops/platform");
  await expect(page).toHaveURL(/\/login$/);

  mode = "forbidden";
  await page.goto("/ops/platform");
  await expect(page.getByText("没有平台诊断权限", { exact: true })).toBeVisible();
  await expect(page.getByLabel("平台就绪证据摘要")).toHaveCount(0);

  mode = "network";
  await page.reload();
  await expect(page.getByText("无法连接平台诊断服务", { exact: true })).toBeVisible();
  await expect(page.getByLabel("平台就绪证据摘要")).toHaveCount(0);
});

test("operator evidence stays reachable without horizontal overflow", async ({ page }) => {
  await page.route("**/api/operator/platform/readiness", (route) => fulfill(route, readiness({
    status: "unsafe_to_serve",
    checks: [{
      ...readiness().checks[0],
      status: "unsafe_to_serve",
      next_action: "Stop rollout, verify Redis credentials, then rerun the platform doctor before restoring traffic.",
    }],
  })));

  await page.goto("/ops/platform");
  await expect(page.getByRole("main", { name: "平台就绪" })).toBeVisible();
  await expect(page.getByRole("button", { name: "刷新平台就绪证据" })).toBeVisible();
  await expect(page.getByText(/Stop rollout, verify Redis credentials/)).toBeVisible();
  const hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(hasOverflow).toBe(false);
});
