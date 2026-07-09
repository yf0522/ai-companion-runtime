import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  traceId?: string;
  ttftMs?: number;
  totalLatencyMs?: number;
  toolsUsed?: string[];
  riskAlert?: { level: string; message: string };
  status: "sending" | "streaming" | "complete" | "error";
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
    toolsUsed: string[];
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
        { id: `ast_${Date.now()}`, role: "assistant", content: "", traceId, status: "streaming" },
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
    // For now just log, Phase 3 will render tool badges
    console.log(`Tool ${tool}: ${status}`);
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
        msgs[msgs.length - 1] = {
          ...last,
          id: data.messageId,
          traceId: data.traceId,
          ttftMs: data.ttftMs,
          totalLatencyMs: data.totalLatencyMs,
          toolsUsed: data.toolsUsed,
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
