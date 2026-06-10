import { create } from "zustand";
import { CompanionWsClient } from "@/lib/ws-client";
import { useChatStore } from "./chatStore";

type WsStatus = "disconnected" | "connecting" | "connected" | "reconnecting" | "failed";

interface WsState {
  status: WsStatus;
  sessionId: string | null;
  client: CompanionWsClient | null;

  connect: (token?: string) => void;
  disconnect: () => void;
  sendMessage: (message: string) => void;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export const useWsStore = create<WsState>((set, get) => ({
  status: "disconnected",
  sessionId: null,
  client: null,

  connect: (token = "dev-token") => {
    const existing = get().client;
    if (existing) existing.disconnect();

    const client = new CompanionWsClient(WS_URL);

    // Status changes
    client.on("_status", (data) => {
      set({ status: data.status as WsStatus });
    });

    // Connected
    client.on("connected", (data) => {
      set({ sessionId: data.session_id, status: "connected" });
    });

    // Trace ID
    client.on("trace", (data) => {
      useChatStore.getState().startAssistantMessage(data.trace_id);
    });

    // Risk alert
    client.on("risk_alert", (data) => {
      useChatStore.getState().setRiskAlert(data.level, data.message);
    });

    // First reply
    client.on("first_reply", (data) => {
      useChatStore.getState().setFirstReply(data.text, data.ttft_ms);
    });

    // Delta
    client.on("delta", (data) => {
      useChatStore.getState().appendDelta(data.text);
    });

    // Tool status
    client.on("tool_status", (data) => {
      useChatStore.getState().setToolStatus(data.tool, data.status);
    });

    // Final
    client.on("final", (data) => {
      useChatStore.getState().finalizeMessage({
        traceId: data.trace_id,
        messageId: data.message_id,
        ttftMs: data.ttft_ms,
        totalLatencyMs: data.total_latency_ms,
        toolsUsed: data.tools_used || [],
        memoryUpdated: data.memory_updated || false,
      });
    });

    // Error
    client.on("error", (data) => {
      useChatStore.getState().setError(data.message);
    });

    set({ client, status: "connecting" });
    client.connect(token);
  },

  disconnect: () => {
    get().client?.disconnect();
    set({ client: null, status: "disconnected", sessionId: null });
  },

  sendMessage: (message) => {
    const { client } = get();
    if (client) {
      useChatStore.getState().addUserMessage(message);
      client.sendMessage(message);
    }
  },
}));
