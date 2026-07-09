import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ToolChipStatus =
  | "calling"
  | "success"
  | "failed"
  | "timeout"
  | "needs_clarification";

export interface ToolChip {
  tool: string;
  status: ToolChipStatus;
  action?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  traceId?: string;
  ttftMs?: number;
  totalLatencyMs?: number;
  toolsUsed?: ToolChip[];
  riskAlert?: { level: string; message: string };
  status: "sending" | "streaming" | "complete" | "error";
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
    return action ? { tool, status, action } : { tool, status };
  }
  return null;
}

function upsertToolChip(chips: ToolChip[], tool: string, status: string): ToolChip[] {
  const chip = normalizeToolChip({ tool, status });
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

interface ChatState {
  messages: Message[];
  currentTraceId: string | null;
  isStreaming: boolean;

  addUserMessage: (content: string) => string;
  startAssistantMessage: (traceId: string) => void;
  appendDelta: (text: string) => void;
  setFirstReply: (text: string, ttftMs: number) => void;
  setToolStatus: (tool: string, status: string) => void;
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
        msgs[msgs.length - 1] = {
          ...last,
          toolsUsed: upsertToolChip(last.toolsUsed || [], tool, status),
        };
      }
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
          chips = upsertToolChip(chips, chip.tool, chip.status);
          const idx = chips.findIndex((c) => c.tool === chip.tool);
          if (idx >= 0 && chip.action) {
            chips[idx] = { ...chips[idx], action: chip.action };
          }
        }
        msgs[msgs.length - 1] = {
          ...last,
          id: data.messageId,
          traceId: data.traceId,
          ttftMs: data.ttftMs,
          totalLatencyMs: data.totalLatencyMs,
          toolsUsed: chips,
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
