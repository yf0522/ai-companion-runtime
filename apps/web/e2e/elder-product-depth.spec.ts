import { expect, test, type Page } from "@playwright/test";

function tokenFor(role: string) {
  const payload = Buffer.from(JSON.stringify({ sub: `test-${role}`, username: `${role}-review`, role })).toString("base64url");
  return `header.${payload}.signature`;
}

async function seedElder(page: Page) {
  await page.addInitScript(({ token }) => {
    localStorage.setItem("companion-auth", JSON.stringify({
      state: { hydrated: true, token, userId: "test-elder", username: "elder-review", role: "elder" },
      version: 0,
    }));
  }, { token: tokenFor("elder") });
}

async function installMockWebSocket(page: Page, mode: "connected" | "failed") {
  await page.addInitScript(({ wsMode }) => {
    if (wsMode === "failed") {
      const nativeSetTimeout = window.setTimeout.bind(window);
      window.setTimeout = ((handler: TimerHandler, timeout = 0, ...args: unknown[]) => (
        nativeSetTimeout(handler, timeout >= 1_000 ? 1 : timeout, ...args)
      )) as typeof window.setTimeout;
    }

    class MockWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSING = 2;
      readonly CLOSED = 3;
      readyState = MockWebSocket.CONNECTING;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;

      constructor(_url: string | URL) {
        queueMicrotask(() => {
          if (wsMode === "failed") {
            this.readyState = MockWebSocket.CLOSED;
            this.onclose?.(new CloseEvent("close"));
            return;
          }
          this.readyState = MockWebSocket.OPEN;
          this.onopen?.(new Event("open"));
        });
      }

      send(data: string | ArrayBufferLike | Blob | ArrayBufferView) {
        const payload = JSON.parse(String(data));
        if (payload.type === "auth") {
          this.emit({ type: "connected", session_id: "session-1", agent_runtime: "harness" });
        }
        if (payload.type === "user_message") {
          this.emit({ type: "trace", trace_id: "trace-1" });
          this.emit({ type: "delta", text: "我正在确认这件事。" });
        }
      }

      close() {
        this.readyState = MockWebSocket.CLOSED;
        this.onclose?.(new CloseEvent("close"));
      }

      addEventListener() {}
      removeEventListener() {}
      dispatchEvent() { return true; }

      private emit(payload: object) {
        queueMicrotask(() => this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) })));
      }
    }

    Object.defineProperty(window, "WebSocket", { configurable: true, value: MockWebSocket });
  }, { wsMode: mode });
}

async function json(page: Page, matcher: string | RegExp, body: unknown) {
  await page.route(matcher, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  }));
}

test("reconnecting elder can keep editing a compact action-dock draft", async ({ page }) => {
  await seedElder(page);
  await page.goto("/elder/companion");

  await expect(page.getByLabel("选择回应方式")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "记忆与隐私" })).toBeVisible();
  const input = page.getByLabel("输入给陪伴助手的消息");
  await input.fill("连接恢复后还要保留这句话");
  await input.press("Enter");
  await expect(input).toContainText("连接恢复后还要保留这句话");

  const composer = page.locator(".astryx-chat-composer");
  const box = await composer.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.height).toBeGreaterThanOrEqual(60);
  expect(box!.height).toBeLessThanOrEqual(76);
  await expect(page.locator(".astryx-chat-layout-scroll-button")).toHaveCount(0);
  const dictationButton = page.getByRole("button", { name: "开始语音输入" });
  if (await dictationButton.count()) {
    await expect(dictationButton).toBeVisible();
  } else {
    await expect(page.getByText("当前浏览器不支持语音输入，可以继续打字")).toBeVisible();
  }
});

test("connected action dock expands for a long draft and exposes streaming control", async ({ page }) => {
  await installMockWebSocket(page, "connected");
  await seedElder(page);
  await page.goto("/elder/companion");

  await expect(page.getByText("连接正常，由你确认后才会发送", { exact: true })).toBeVisible();
  const input = page.getByLabel("输入给陪伴助手的消息");
  await input.fill("请先帮我确认这通电话是不是诈骗。\n对方一直催我转账，还要我提供验证码。\n我还没有进行任何操作。");
  const expanded = await page.locator(".astryx-chat-composer").boundingBox();
  expect(expanded).not.toBeNull();
  expect(expanded!.height).toBeGreaterThan(60);
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByRole("button", { name: "停止回复" })).toBeVisible();
  await expect(page.getByRole("log")).toContainText("我正在确认这件事。");
});

test("failed action dock preserves the draft and offers an explicit retry", async ({ page }) => {
  await installMockWebSocket(page, "failed");
  await seedElder(page);
  await page.goto("/elder/companion");

  await expect(page.getByText("暂时无法连接，草稿已保留", { exact: true })).toBeVisible();
  const input = page.getByLabel("输入给陪伴助手的消息");
  await input.fill("这句话不能因为连接失败而丢失");
  await input.press("Enter");
  await expect(input).toContainText("这句话不能因为连接失败而丢失");
  await expect(page.getByRole("button", { name: "重新连接" })).toBeVisible();
});

test("dictation-unsupported browsers keep the complete text fallback", async ({ page }) => {
  await page.addInitScript(() => {
    Reflect.deleteProperty(window, "SpeechRecognition");
    Reflect.deleteProperty(window, "webkitSpeechRecognition");
  });
  await installMockWebSocket(page, "connected");
  await seedElder(page);
  await page.goto("/elder/companion");

  await expect(page.getByText("当前浏览器不支持语音输入，可以继续打字", { exact: true })).toBeVisible();
  const input = page.getByLabel("输入给陪伴助手的消息");
  await input.fill("语音不可用时仍然可以完整输入这句话");
  await expect(input).toContainText("语音不可用时仍然可以完整输入这句话");
});

test("elder today uses canonical states and offers legal recovery actions", async ({ page }) => {
  await seedElder(page);
  await json(page, /\/api\/care-tasks(?:\?.*)?$/, {
    user_id: "test-elder",
    scope: "today",
    total: 6,
    items: [
      { id: "pending", title: "早餐后吃药", status: "pending", due_at: "2026-07-11T08:00:00Z", version: 1 },
      { id: "due", title: "现在测血压", status: "due", due_at: "2026-07-11T09:00:00Z", version: 1 },
      { id: "snoozed", title: "稍后喝水", status: "snoozed", snooze_until: "2026-07-11T10:00:00Z", version: 1 },
      { id: "missed", title: "错过的复诊确认", status: "missed", due_at: "2026-07-11T07:00:00Z", version: 1 },
      { id: "done", title: "已经完成的事项", status: "done", completed_at: "2026-07-11T07:30:00Z", version: 2 },
      { id: "cancelled", title: "已经取消的事项", status: "cancelled", version: 2 },
    ],
  });
  await page.goto("/elder/today");

  for (const label of ["已安排", "现在需要处理", "已延后", "已错过"]) {
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  }
  await expect(page.getByText("已经完成的事项", { exact: true })).toHaveCount(0);
  await expect(page.getByText("已经取消的事项", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "晚 30 分钟提醒" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "需要帮助" }).first()).toBeVisible();
});

test("elder help exposes only verified named direct contacts", async ({ page }) => {
  await seedElder(page);
  await json(page, /\/api\/contacts(?:\?.*)?$/, {
    total: 2,
    items: [
      { id: "verified", name: "女儿 小林", channel: "phone", value: "+86 13800000000", verification_status: "verified", available: true, escalation_order: 1, last_verified_at: "2026-07-10T08:00:00Z" },
      { id: "pending", name: "待验证联系人", channel: "phone", value: "+86 13900000000", verification_status: "pending", available: true, escalation_order: 2, last_verified_at: null },
    ],
  });
  await page.goto("/elder/help");

  await expect(page.getByText("女儿 小林", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "打电话给女儿 小林" })).toHaveAttribute("href", "tel:+8613800000000");
  await expect(page.getByText("待验证联系人", { exact: true })).toHaveCount(0);
});

test("owner Memory Center supports pending consent and local-record clearing", async ({ page }) => {
  await seedElder(page);
  await json(page, /\/api\/memory\/memories(?:\?.*)?$/, {
    user_id: "test-elder",
    memories: [
      { id: "pending-memory", content: "我喜欢听评书", type: "preference", purpose: "care_continuity", sensitivity: "general", consent_status: "pending", deletion_state: "active", correction_state: "original", created_at: "2026-07-11T08:00:00Z" },
      { id: "granted-memory", content: "我习惯早饭后散步", type: "routine", purpose: "care_continuity", sensitivity: "general", consent_status: "granted", deletion_state: "active", correction_state: "original", created_at: "2026-07-10T08:00:00Z" },
    ],
  });
  await page.goto("/elder/memory");

  await expect(page.getByText("我喜欢听评书", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "同意保留" })).toBeVisible();
  await expect(page.getByRole("button", { name: "不保留" })).toBeVisible();
  await expect(page.getByRole("button", { name: "修改内容" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "删除记忆" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "清除本机对话记录" })).toBeVisible();
});
