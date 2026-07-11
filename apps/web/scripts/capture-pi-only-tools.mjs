import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webRoot, "../..");
const outputDir = path.join(repoRoot, ".omx/artifacts/visual-ralph/pi-only-tools");
const baseUrl = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3018";

fs.mkdirSync(outputDir, { recursive: true });

function tokenFor(role) {
  const payload = Buffer.from(JSON.stringify({ sub: `test-${role}`, username: `${role}-review`, role })).toString("base64url");
  return `header.${payload}.signature`;
}

/** Seeded companion chat states for the three frozen Phase 4 flows. */
const FLOWS = {
  memory: {
    filename: "actual-memory-note-recall.png",
    reference: "reference-memory-note-recall.png",
    messages: [
      {
        id: "u-mem",
        role: "user",
        content: "请记住我对青霉素过敏",
        status: "complete",
      },
      {
        id: "a-mem",
        role: "assistant",
        content: "好的，我已经记下你对青霉素过敏。之后开药或提醒时会先核对这条记忆。",
        status: "complete",
        toolsUsed: [
          { tool: "memory", status: "success", action: "记下过敏史" },
        ],
      },
      {
        id: "u-mem-2",
        role: "user",
        content: "我有什么过敏来着？",
        status: "complete",
      },
      {
        id: "a-mem-2",
        role: "assistant",
        content: "你说过对青霉素过敏。需要的话我可以再帮你确认一次。",
        status: "complete",
        toolsUsed: [
          { tool: "memory", status: "success", action: "召回过敏史" },
        ],
      },
    ],
  },
  caretask: {
    filename: "actual-caretask-list-create.png",
    reference: "reference-caretask-list-create.png",
    messages: [
      {
        id: "u-care",
        role: "user",
        content: "提醒我晚上八点吃药",
        status: "complete",
      },
      {
        id: "a-care",
        role: "assistant",
        content: "已为你创建晚上八点的吃药提醒。也可以说“看看今天的安排”查看列表。",
        status: "complete",
        toolsUsed: [
          { tool: "caretask", status: "success", action: "创建吃药提醒" },
        ],
      },
      {
        id: "u-care-2",
        role: "user",
        content: "我今天需要做什么",
        status: "complete",
      },
      {
        id: "a-care-2",
        role: "assistant",
        content: "今天还有一项：晚上八点吃药。到点我会提醒你。",
        status: "complete",
        toolsUsed: [
          { tool: "caretask", status: "success", action: "列出今日安排" },
        ],
      },
    ],
  },
  utility: {
    filename: "actual-utility-action.png",
    reference: "reference-utility-action.png",
    messages: [
      {
        id: "u-util",
        role: "user",
        content: "北京今天天气怎么样",
        status: "complete",
      },
      {
        id: "a-util",
        role: "assistant",
        content: "北京今天多云，气温大约 18–26℃，出门记得带件薄外套。",
        status: "complete",
        toolsUsed: [
          { tool: "utility", status: "success", action: "天气查询" },
        ],
      },
    ],
  },
};

async function createCompanionPage(browser, flowKey, viewport) {
  const flow = FLOWS[flowKey];
  const context = await browser.newContext({ viewport });
  await context.addInitScript(({ seededRole, token, messages }) => {
    localStorage.setItem("companion-auth", JSON.stringify({
      state: {
        hydrated: true,
        token,
        userId: `test-${seededRole}`,
        username: `${seededRole}-review`,
        role: seededRole,
      },
      version: 0,
    }));
    localStorage.setItem("companion.agent_runtime", "pi_experimental");
    localStorage.setItem("companion-chat", JSON.stringify({
      state: { messages },
      version: 0,
    }));
  }, {
    seededRole: "elder",
    token: tokenFor("elder"),
    messages: flow.messages,
  });
  // Avoid hanging on a live WS during screenshot capture.
  await context.route("**/ws/**", (route) => route.abort());
  const page = await context.newPage();
  return { context, page, flow };
}

async function removeDevelopmentChrome(page) {
  await page.addStyleTag({ content: "nextjs-portal,[data-next-badge-root]{display:none!important}" }).catch(() => {});
}

async function captureFlow(browser, flowKey, viewport, filename) {
  const { context, page, flow } = await createCompanionPage(browser, flowKey, viewport);
  await page.goto(`${baseUrl}/elder/companion`, { waitUntil: "networkidle" });
  await removeDevelopmentChrome(page);
  // Assert chip copy is present before screenshot (fails capture early if UI regresses).
  const family = flowKey === "memory" ? "memory" : flowKey === "caretask" ? "caretask" : "utility";
  await page.getByText(new RegExp(family, "i")).first().waitFor({ timeout: 15000 });
  await page.getByLabel("选择回应方式").waitFor({ state: "detached", timeout: 2000 }).catch(() => {});
  const outPath = path.join(outputDir, filename || flow.filename);
  await page.screenshot({ path: outPath, fullPage: false });
  // First successful capture also seeds the reference baseline for Visual Ralph.
  const refPath = path.join(outputDir, flow.reference);
  if (!fs.existsSync(refPath)) {
    fs.copyFileSync(outPath, refPath);
  }
  await context.close();
  return outPath;
}

const browser = await chromium.launch({ headless: true });
const desktop = { width: 1440, height: 1000 };
const results = [];
try {
  for (const key of Object.keys(FLOWS)) {
    const out = await captureFlow(browser, key, desktop, FLOWS[key].filename);
    results.push(out);
    console.log(`captured ${key}: ${out}`);
  }
  // Mobile companion check for memory flow (secondary viewport).
  await captureFlow(browser, "memory", { width: 390, height: 844 }, "actual-memory-note-recall-mobile.png");
  console.log(`captured memory mobile`);
} finally {
  await browser.close();
}

const manifest = {
  slug: "pi-only-tools",
  route: "/elder/companion",
  viewport: desktop,
  flows: Object.fromEntries(
    Object.entries(FLOWS).map(([key, flow]) => [key, {
      actual: flow.filename,
      reference: flow.reference,
      chip_family: key,
    }]),
  ),
  captured_at: new Date().toISOString(),
  base_url: baseUrl,
  outputs: results,
};
fs.writeFileSync(path.join(outputDir, "capture-manifest.json"), JSON.stringify(manifest, null, 2));
console.log(`manifest: ${path.join(outputDir, "capture-manifest.json")}`);
