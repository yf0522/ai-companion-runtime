import http from "node:http";
import { Agent, convertToLlm } from "@earendil-works/pi-agent-core";
import { Type } from "typebox";
import { builtinModels } from "@earendil-works/pi-ai/providers/all";

// pi-ai's Google provider reads GEMINI_API_KEY; align with harness GOOGLE_API_KEY.
if (!process.env.GEMINI_API_KEY && process.env.GOOGLE_API_KEY) {
  process.env.GEMINI_API_KEY = process.env.GOOGLE_API_KEY;
}

const PORT = Number(process.env.PI_SIDECAR_PORT || 8787);
const DEFAULT_MODEL = process.env.PI_MODEL || "gemini-2.5-flash";
const DEFAULT_PROVIDER = process.env.PI_PROVIDER || "google";
const TOOL_BRIDGE_URL =
  process.env.TOOL_BRIDGE_URL || "http://127.0.0.1:8000/api";
const TOOL_BRIDGE_TOKEN = process.env.TOOL_BRIDGE_TOKEN || "";
const ENABLE_TOOLS = process.env.PI_ENABLE_TOOLS !== "0";
const SYSTEM_PROMPT =
  process.env.PI_SYSTEM_PROMPT ||
  [
    "You are a warm, concise AI companion for older adults.",
    "Reply in the user's language. Keep answers practical and kind.",
    "When the user asks about medication, appointments, or care tasks, use the caretask tool.",
    "Never claim a tool succeeded if the tool result status is failed or timeout.",
    "If a tool fails, apologize briefly and ask the user to try again — do not invent success.",
  ].join(" ");

const models = builtinModels();

function resolveModel(provider = DEFAULT_PROVIDER, modelId = DEFAULT_MODEL) {
  const model = models.getModel(provider, modelId);
  if (!model) {
    throw new Error(`Unknown model ${provider}/${modelId}`);
  }
  return model;
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function writeNdjson(res, payload) {
  res.write(`${JSON.stringify(payload)}\n`);
}

function normalizeMessages(body) {
  const raw = Array.isArray(body.messages) ? body.messages : [];
  const messages = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const role = item.role === "assistant" ? "assistant" : "user";
    const content = String(item.content ?? "").trim();
    if (!content) continue;
    messages.push({ role, content, timestamp: Date.now() });
  }
  if (!messages.length) {
    throw new Error("messages must include at least one non-empty entry");
  }
  return messages;
}

async function bridgeExecute(toolName, params, ctx) {
  const headers = { "Content-Type": "application/json" };
  if (TOOL_BRIDGE_TOKEN) {
    headers["X-Tool-Bridge-Token"] = TOOL_BRIDGE_TOKEN;
  }
  const res = await fetch(`${TOOL_BRIDGE_URL.replace(/\/$/, "")}/tools/execute`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      tool_name: toolName,
      params,
      user_id: ctx.userId,
      session_id: ctx.sessionId,
      trace_id: ctx.traceId,
      risk_blocked: Boolean(ctx.riskBlocked),
      risk_level: ctx.riskLevel || null,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return {
      tool_name: toolName,
      status: "failed",
      display_text: data.detail || data.error || `bridge HTTP ${res.status}`,
      data: { reason: "bridge_http_error" },
    };
  }
  return data;
}

function makeCareTaskTool(ctx) {
  return {
    name: "caretask",
    label: "CareTask",
    description:
      "Manage eldercare CareTasks (medication/appointment): create, list, complete, snooze, cancel. Reminder is scheduling projection only.",
    parameters: Type.Object({
      action: Type.Union([
        Type.Literal("create"),
        Type.Literal("list"),
        Type.Literal("complete"),
        Type.Literal("snooze"),
        Type.Literal("cancel"),
        Type.Literal("missed"),
      ]),
      title: Type.Optional(Type.String()),
      task_type: Type.Optional(
        Type.Union([
          Type.Literal("medication"),
          Type.Literal("appointment"),
          Type.Literal("other"),
        ]),
      ),
      task_id: Type.Optional(Type.String()),
      due_at: Type.Optional(Type.String()),
      minutes: Type.Optional(Type.Number()),
      notes: Type.Optional(Type.String()),
      query: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params) {
      const result = await bridgeExecute("caretask", params || {}, ctx);
      const status = result.status || "failed";
      const text =
        result.display_text ||
        (status === "success" ? "CareTask ok" : "CareTask failed");
      const isError = status !== "success";
      return {
        content: [{ type: "text", text: `[${status}] ${text}` }],
        details: {
          status,
          data: result.data ?? null,
          tool_name: "caretask",
          display_text: text,
        },
        // Do not terminate early on failure — model must see failure and not invent success.
        terminate: false,
      };
    },
  };
}

async function streamAgentChat({ res, body }) {
  const model = resolveModel(body.provider, body.model);
  const userMessages = normalizeMessages(body);
  const lastUser = userMessages[userMessages.length - 1];
  const ctx = {
    userId: body.user_id || null,
    sessionId: body.session_id || null,
    traceId: body.trace_id || null,
    riskBlocked: Boolean(body.risk_blocked),
    riskLevel: body.risk_level || null,
  };

  const tools = ENABLE_TOOLS ? [makeCareTaskTool(ctx)] : [];
  const toolsUsed = [];

  res.writeHead(200, {
    "Content-Type": "application/x-ndjson; charset=utf-8",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
    "X-Pi-Bridge": "pi-agent-core",
  });

  const agent = new Agent({
    initialState: {
      systemPrompt: body.system || SYSTEM_PROMPT,
      model,
      thinkingLevel: "off",
      tools,
      messages: [],
    },
    convertToLlm,
    toolExecution: "sequential",
    beforeToolCall: async ({ toolCall }) => {
      if (ctx.riskBlocked || ["high", "critical"].includes(String(ctx.riskLevel || "").toLowerCase())) {
        return {
          block: true,
          reason: "risk_blocked: high/critical risk cannot execute tools",
        };
      }
      if (!ENABLE_TOOLS) {
        return { block: true, reason: "tools_disabled" };
      }
      writeNdjson(res, {
        type: "tool_status",
        tool: toolCall.name,
        status: "calling",
      });
      return undefined;
    },
    afterToolCall: async ({ toolCall, result, isError }) => {
      const details = result?.details || {};
      const status =
        details.status || (isError ? "failed" : "success");
      const action = details?.data?.action || null;
      toolsUsed.push({
        tool: toolCall.name,
        status,
        ...(action ? { action } : {}),
      });
      writeNdjson(res, {
        type: "tool_status",
        tool: toolCall.name,
        status,
      });
      if (details.display_text) {
        writeNdjson(res, {
          type: "tool_result",
          tool: toolCall.name,
          text: details.display_text,
          status,
        });
      }
      // Clarification: not a hard error — model should ask user to pick, not invent success.
      if (status === "needs_clarification") {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text:
                result?.content?.[0]?.text ||
                `[needs_clarification] ${details.display_text || "请让用户选择具体任务"}`,
            },
          ],
        };
      }
      // If tool failed, force isError so the model sees failure clearly.
      if (status !== "success") {
        return {
          isError: true,
          content: [
            {
              type: "text",
              text:
                result?.content?.[0]?.text ||
                `[failed] ${details.display_text || toolCall.name + " failed"}`,
            },
          ],
        };
      }
      return undefined;
    },
  });

  agent.subscribe(async (event) => {
    if (
      event.type === "message_update" &&
      event.assistantMessageEvent?.type === "text_delta" &&
      event.assistantMessageEvent.delta
    ) {
      writeNdjson(res, {
        type: "text_delta",
        delta: event.assistantMessageEvent.delta,
      });
    } else if (event.type === "agent_end") {
      writeNdjson(res, {
        type: "done",
        reason: "agent_end",
        tools_used: toolsUsed,
      });
    }
  });

  try {
    await agent.prompt(lastUser.content);
    await agent.waitForIdle();
  } catch (err) {
    writeNdjson(res, {
      type: "error",
      message: err instanceof Error ? err.message : "pi agent error",
    });
  }
  if (!res.writableEnded) {
    res.end();
  }
}

/** Legacy stream path without agent-core (tools disabled / fallback). */
async function streamChatLegacy({ res, body }) {
  const model = resolveModel(body.provider, body.model);
  const context = {
    systemPrompt: body.system || SYSTEM_PROMPT,
    messages: normalizeMessages(body),
    tools: [],
  };

  res.writeHead(200, {
    "Content-Type": "application/x-ndjson; charset=utf-8",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
    "X-Pi-Bridge": "pi-experimental",
  });

  const stream = models.stream(model, context);
  for await (const event of stream) {
    if (event.type === "text_delta" && event.delta) {
      writeNdjson(res, { type: "text_delta", delta: event.delta });
    } else if (event.type === "error") {
      writeNdjson(res, {
        type: "error",
        message: event.error?.errorMessage || "pi-ai stream error",
      });
      break;
    } else if (event.type === "done") {
      writeNdjson(res, { type: "done", reason: event.reason, tools_used: [] });
      break;
    }
  }
  res.end();
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          status: "ok",
          bridge: ENABLE_TOOLS ? "pi-agent-core" : "pi-experimental",
          provider: DEFAULT_PROVIDER,
          model: DEFAULT_MODEL,
          tools: ENABLE_TOOLS ? ["caretask"] : [],
        }),
      );
      return;
    }

    if (req.method === "POST" && req.url === "/v1/chat") {
      const body = await readJson(req);
      const useAgent = body.use_agent_core !== false && ENABLE_TOOLS;
      if (body.stream === false) {
        // Non-stream: still use agent path into a buffer.
        const chunks = [];
        const fakeRes = {
          headersSent: false,
          writableEnded: false,
          writeHead() {
            this.headersSent = true;
          },
          write(chunk) {
            chunks.push(chunk);
          },
          end() {
            this.writableEnded = true;
          },
        };
        if (useAgent) {
          await streamAgentChat({ res: fakeRes, body: { ...body, stream: true } });
        } else {
          await streamChatLegacy({ res: fakeRes, body });
        }
        let text = "";
        const tools_used = [];
        for (const line of chunks.join("").split("\n")) {
          if (!line.trim()) continue;
          try {
            const ev = JSON.parse(line);
            if (ev.type === "text_delta") text += ev.delta || "";
            if (ev.type === "done" && Array.isArray(ev.tools_used)) {
              tools_used.push(...ev.tools_used);
            }
          } catch {
            /* ignore */
          }
        }
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ type: "text", text, tools_used }));
        return;
      }
      if (useAgent) {
        await streamAgentChat({ res, body });
        return;
      }
      await streamChatLegacy({ res, body });
      return;
    }

    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not_found" }));
  } catch (err) {
    const message = err instanceof Error ? err.message : "sidecar_error";
    if (!res.headersSent) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: message }));
      return;
    }
    writeNdjson(res, { type: "error", message });
    res.end();
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(
    `[pi-sidecar] listening on http://127.0.0.1:${PORT} (${DEFAULT_PROVIDER}/${DEFAULT_MODEL}) tools=${ENABLE_TOOLS ? "caretask" : "off"}`,
  );
});
