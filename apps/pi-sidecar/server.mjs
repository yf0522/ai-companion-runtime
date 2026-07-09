import http from "node:http";
import { builtinModels } from "@earendil-works/pi-ai/providers/all";

// pi-ai's Google provider reads GEMINI_API_KEY; align with harness GOOGLE_API_KEY.
if (!process.env.GEMINI_API_KEY && process.env.GOOGLE_API_KEY) {
  process.env.GEMINI_API_KEY = process.env.GOOGLE_API_KEY;
}

const PORT = Number(process.env.PI_SIDECAR_PORT || 8787);
const DEFAULT_MODEL = process.env.PI_MODEL || "gemini-2.5-flash";
const DEFAULT_PROVIDER = process.env.PI_PROVIDER || "google";
const SYSTEM_PROMPT =
  process.env.PI_SYSTEM_PROMPT ||
  "You are a warm, concise AI companion for older adults. Reply in the user's language, keep answers practical and kind.";

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

async function streamChat({ res, body }) {
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
      writeNdjson(res, { type: "done", reason: event.reason });
      break;
    }
  }
  res.end();
}

async function completeChat(body) {
  const model = resolveModel(body.provider, body.model);
  const context = {
    systemPrompt: body.system || SYSTEM_PROMPT,
    messages: normalizeMessages(body),
    tools: [],
  };

  let text = "";
  const stream = models.stream(model, context);
  for await (const event of stream) {
    if (event.type === "text_delta" && event.delta) {
      text += event.delta;
    } else if (event.type === "error") {
      throw new Error(event.error?.errorMessage || "pi-ai stream error");
    } else if (event.type === "done") {
      break;
    }
  }
  return { type: "text", text };
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          status: "ok",
          bridge: "pi-experimental",
          provider: DEFAULT_PROVIDER,
          model: DEFAULT_MODEL,
        }),
      );
      return;
    }

    if (req.method === "POST" && req.url === "/v1/chat") {
      const body = await readJson(req);
      if (body.stream !== false) {
        await streamChat({ res, body });
        return;
      }
      const payload = await completeChat(body);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(payload));
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
    `[pi-sidecar] listening on http://127.0.0.1:${PORT} (${DEFAULT_PROVIDER}/${DEFAULT_MODEL})`,
  );
});
