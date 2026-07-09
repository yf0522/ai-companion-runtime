import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ToolChipStatus =
  | "calling"
  | "success"
  | "failed"
  | "timeout"
  | "needs_clarification";

export interface CareTaskCandidate {
  id: string;
  title: string;
  status?: string;
  due_at?: string | null;
  task_type?: string;
}

export interface ToolChip {
  tool: string;
  status: ToolChipStatus;
  action?: string;
  candidates?: CareTaskCandidate[];
  clarifyVerb?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  traceId?: string;
  ttftMs?: number;
  totalLatencyMs?: number;
  toolsUsed?: ToolChip[];
  careTaskClarify?: {
    verb: string;
    candidates: CareTaskCandidate[];
  };
  riskAlert?: { level: string; message: string };
  status: "sending" | "streaming" | "complete" | "error";
}

function normalizeCandidates(raw: unknown): CareTaskCandidate[] | undefined {
  if (!Array.isArray(raw) || raw.length === 0) return undefined;
  const out: CareTaskCandidate[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const obj = item as Record<string, unknown>;
    const id = String(obj.id || "").trim();
    const title = String(obj.title || "").trim();
    if (!id || !title) continue;
    out.push({
      id,
      title,
      status: obj.status ? String(obj.status) : undefined,
      due_at: obj.due_at == null ? null : String(obj.due_at),
      task_type: obj.task_type ? String(obj.task_type) : undefined,
    });
  }
  return out.length ? out : undefined;
}

function normalizeToolChip(raw: unknown): ToolChip | null {
  if (typeof raw === "string" && raw.trim()) {
    // Legacy string[] — never auto-✓; treat as neutral calling until known.
    return { tool: raw, status: "calling" };
  }
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    const tool = String(obj.tool || obj.tool_name || "").trim();
    if (!tool) return null;
    const statusRaw = String(obj.status || "calling");
    const allowed: ToolChipStatus[] = [
      "calling",
      "success",
      "failed",
      "timeout",
      "needs_clarification",
    ];
    const status = (allowed.includes(statusRaw as ToolChipStatus)
      ? statusRaw
      : "calling") as ToolChipStatus;
    const action = obj.action ? String(obj.action) : undefined;
    const candidates = normalizeCandidates(obj.candidates);
    const clarifyVerb = obj.clarify_verb
      ? String(obj.clarify_verb)
      : obj.clarifyVerb
        ? String(obj.clarifyVerb)
        : undefined;
    const chip: ToolChip = { tool, status };
    if (action) chip.action = action;
    if (candidates) chip.candidates = candidates;
    if (clarifyVerb) chip.clarifyVerb = clarifyVerb;
    return chip;
  }
  return null;
}

function upsertToolChip(
  chips: ToolChip[],
  tool: string,
  status: string,
  extra?: Partial<ToolChip>,
): ToolChip[] {
  const chip = normalizeToolChip({ tool, status, ...extra });
  if (!chip) return chips;
  const next = [...chips];
  const idx = next.findIndex((c) => c.tool === tool);
  if (idx >= 0) {
    next[idx] = { ...next[idx], ...chip };
  } else {
    next.push(chip);
  }
  return next;
}

function clarifyFromChips(chips: ToolChip[] | undefined): Message["careTaskClarify"] {
  if (!chips) return undefined;
  for (const chip of chips) {
    if (
      chip.status === "needs_clarification" &&
      chip.candidates &&
      chip.candidates.length > 0
    ) {
      return {
        verb: chip.clarifyVerb || "确认",
        candidates: chip.candidates,
      };
    }
  }
  return undefined;
}

interface ChatState {
  messages: Message[];
  currentTraceId: string | null;
  isStreaming: boolean;

  addUserMessage: (content: string) => string;
  startAssistantMessage: (traceId: string) => void;
  appendDelta: (text: string) => void;
  setFirstReply: (text: string, ttftMs: number) => void;
  setToolStatus: (tool: string, status: string) => void;
  setToolResult: (data: {
    tool: string;
    status?: string;
    text?: string;
    action?: string;
    candidates?: unknown;
    clarifyVerb?: string;
  }) => void;
  setRiskAlert: (level: string, message: string) => void;
  finalizeMessage: (data: {
    traceId: string;
    messageId: string;
    ttftMs: number;
    totalLatencyMs: number;
    toolsUsed: unknown[];
    memoryUpdated: boolean;
  }) => void;
  setError: (message: string) => void;
  resetStreaming: () => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
  messages: [],
  currentTraceId: null,
  isStreaming: false,

  addUserMessage: (content) => {
    const id = `user_${Date.now()}`;
    set((s) => ({
      messages: [...s.messages, { id, role: "user", content, status: "complete" }],
    }));
    return id;
  },

  startAssistantMessage: (traceId) => {
    set((s) => ({
      currentTraceId: traceId,
      isStreaming: true,
      messages: [
        ...s.messages,
        {
          id: `ast_${Date.now()}`,
          role: "assistant",
          content: "",
          traceId,
          status: "streaming",
          toolsUsed: [],
        },
      ],
    }));
  },

  setFirstReply: (text, ttftMs) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant" && last.status === "streaming") {
        msgs[msgs.length - 1] = { ...last, content: text, ttftMs };
      }
      return { messages: msgs };
    });
  },

  appendDelta: (text) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant" && last.status === "streaming") {
        msgs[msgs.length - 1] = { ...last, content: last.content + text };
      }
      return { messages: msgs };
    });
  },

  setToolStatus: (tool, status) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        const toolsUsed = upsertToolChip(last.toolsUsed || [], tool, status);
        msgs[msgs.length - 1] = {
          ...last,
          toolsUsed,
          careTaskClarify: clarifyFromChips(toolsUsed) || last.careTaskClarify,
        };
      }
      return { messages: msgs };
    });
  },

  setToolResult: (data) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role !== "assistant") return {};
      const status = data.status || "success";
      const candidates = normalizeCandidates(data.candidates);
      const toolsUsed = upsertToolChip(last.toolsUsed || [], data.tool, status, {
        action: data.action,
        candidates,
        clarifyVerb: data.clarifyVerb,
      });
      const careTaskClarify =
        status === "needs_clarification" && candidates
          ? {
              verb: data.clarifyVerb || "确认",
              candidates,
            }
          : clarifyFromChips(toolsUsed) || last.careTaskClarify;
      msgs[msgs.length - 1] = {
        ...last,
        toolsUsed,
        careTaskClarify,
      };
      return { messages: msgs };
    });
  },

  setRiskAlert: (level, message) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, riskAlert: { level, message } };
      }
      return { messages: msgs };
    });
  },

  finalizeMessage: (data) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant" && last.status === "streaming") {
        const fromFinal = (data.toolsUsed || [])
          .map(normalizeToolChip)
          .filter((c): c is ToolChip => c !== null);
        // Prefer live chip statuses; merge final outcomes by tool name.
        let chips = [...(last.toolsUsed || [])];
        for (const chip of fromFinal) {
          chips = upsertToolChip(chips, chip.tool, chip.status, {
            action: chip.action,
            candidates: chip.candidates,
            clarifyVerb: chip.clarifyVerb,
          });
        }
        msgs[msgs.length - 1] = {
          ...last,
          id: data.messageId,
          traceId: data.traceId,
          ttftMs: data.ttftMs,
          totalLatencyMs: data.totalLatencyMs,
          toolsUsed: chips,
          careTaskClarify: clarifyFromChips(chips) || last.careTaskClarify,
          status: "complete",
        };
      }
      return { messages: msgs, isStreaming: false, currentTraceId: null };
    });
  },

  setError: (message) => {
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant" && last.status === "streaming") {
        msgs[msgs.length - 1] = { ...last, content: message, status: "error" };
      }
      return { messages: msgs, isStreaming: false };
    });
  },

  resetStreaming: () => {
    set((s) => {
      if (!s.isStreaming) return {};
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant" && last.status === "streaming") {
        msgs[msgs.length - 1] = { ...last, status: "error", content: last.content || "(连接中断，请重试)" };
      }
      return { messages: msgs, isStreaming: false, currentTraceId: null };
    });
  },

  clearMessages: () => set({ messages: [], currentTraceId: null, isStreaming: false }),
}),
    {
      name: "companion-chat",
      partialize: (state) => ({ messages: state.messages.filter((m) => m.status === "complete") }),
    }
  )
);
