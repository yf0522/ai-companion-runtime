import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webRoot, "../..");
const outputDir = path.join(repoRoot, ".omx/artifacts/visual-ralph/quiet-care");
const baseUrl = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3017";

fs.mkdirSync(outputDir, { recursive: true });

function tokenFor(role) {
  const payload = Buffer.from(JSON.stringify({ sub: `test-${role}`, username: `${role}-review`, role })).toString("base64url");
  return `header.${payload}.signature`;
}

async function createPage(browser, role, viewport) {
  const context = await browser.newContext({ viewport });
  if (role) {
    await context.addInitScript(({ seededRole, token }) => {
      localStorage.setItem("companion-auth", JSON.stringify({
        state: { hydrated: true, token, userId: `test-${seededRole}`, username: `${seededRole}-review`, role: seededRole },
        version: 0,
      }));
      localStorage.removeItem("companion.agent_runtime");
    }, { seededRole: role, token: tokenFor(role) });
  }
  return { context, page: await context.newPage() };
}

async function removeDevelopmentChrome(page) {
  await page.addStyleTag({ content: "nextjs-portal,[data-next-badge-root]{display:none!important}" }).catch(() => {});
}

async function captureFamily(browser, viewport, filename) {
  const { context, page } = await createPage(browser, "family", viewport);
  await page.route("**/api/care-tasks", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify([{
      id: "task-1",
      title: "晚间降压药",
      status: "scheduled",
      next_fire_at: "2026-07-10T20:00:00Z",
      schedule_type: "daily",
      created_by: "family",
      version: 1,
    }]),
  }));
  await page.route("**/api/notifications", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      user_id: "elder-1",
      total: 1,
      status: "persisted",
      items: [{
        id: "alert-1",
        user_id: "elder-1",
        category: "scam_alert",
        title: "疑似转账诈骗",
        message: "对方要求立即转账并索取验证码。Companion 已暂停相关操作，并把情况同步给家人。",
        trace_id: "trace-1",
        severity: "high",
        status: "delivered",
        created_at: "2026-07-10T08:00:00Z",
      }],
    }),
  }));
  await page.goto(`${baseUrl}/family/overview`, { waitUntil: "networkidle" });
  await removeDevelopmentChrome(page);
  await page.screenshot({ path: path.join(outputDir, filename) });
  await context.close();
}

async function captureRoute(browser, { role, route, filename, setup, viewport = { width: 1440, height: 1000 } }) {
  const { context, page } = await createPage(browser, role, viewport);
  if (setup) await setup(page);
  await page.goto(`${baseUrl}${route}`, { waitUntil: "networkidle" });
  await removeDevelopmentChrome(page);
  await page.screenshot({ path: path.join(outputDir, filename) });
  await context.close();
}

const browser = await chromium.launch({ headless: true });
try {
  await captureFamily(browser, { width: 1440, height: 1000 }, "actual-family-desktop.png");
  await captureFamily(browser, { width: 390, height: 844 }, "actual-family-mobile.png");
  await captureRoute(browser, { role: null, route: "/login", filename: "actual-login-desktop.png" });
  await captureRoute(browser, { role: "elder", route: "/elder/companion", filename: "actual-elder-desktop.png" });
  await captureRoute(browser, {
    role: "elder",
    route: "/elder/companion",
    filename: "actual-elder-tablet.png",
    viewport: { width: 768, height: 1024 },
  });
  await captureRoute(browser, {
    role: "family",
    route: "/family/alerts",
    filename: "actual-family-alerts-mobile.png",
    viewport: { width: 390, height: 844 },
    setup: async (page) => {
      await page.route("**/api/notifications", (route) => route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          user_id: "elder-1",
          total: 2,
          status: "persisted",
          items: [
            { id: "alert-delivered", user_id: "elder-1", category: "scam_alert", title: "转账风险", message: "通知已送达家人。", trace_id: "trace-1", severity: "high", status: "delivered", created_at: "2026-07-10T08:00:00Z" },
            { id: "alert-acknowledged", user_id: "elder-1", category: "emotional_low", title: "情绪关怀", message: "家人已确认处理。", trace_id: "trace-2", severity: "medium", status: "acknowledged", created_at: "2026-07-09T08:00:00Z" },
          ],
        }),
      }));
    },
  });
  await captureRoute(browser, {
    role: "operator",
    route: "/ops/care",
    filename: "actual-operator-desktop.png",
    setup: async (page) => {
      await page.route("**/api/operator/cases", (route) => route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          total: 1,
          items: [{
            id: "case-1",
            user_id: "elder-1",
            safety_decision_id: "decision-12345678",
            notification_outbox_id: "outbox-12345678",
            status: "open",
            severity: "critical",
            owner_id: null,
            summary: "高风险诈骗，需要人工确认",
            resolution: null,
            due_at: "2026-07-10T09:00:00Z",
            created_at: "2026-07-10T08:00:00Z",
            resolved_at: null,
            state_version: 1,
          }],
        }),
      }));
    },
  });
} finally {
  await browser.close();
}

console.log(`Quiet Care screenshots written to ${outputDir}`);
