import { create } from "zustand";
import { CompanionWsClient } from "@/lib/ws-client";
import { useChatStore } from "./chatStore";
import { getActiveAgentRuntime, type AgentRuntimeId } from "./agentRuntimeStore";

type WsStatus = "disconnected" | "connecting" | "connected" | "reconnecting" | "failed";

interface WsState {
  status: WsStatus;
  sessionId: string | null;
  activeRuntime: AgentRuntimeId;
  client: CompanionWsClient | null;

  connect: (token?: string) => void;
  disconnect: () => void;
  sendMessage: (message: string) => void;
  stopGeneration: () => void;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8001";
const TOOL_TURN_FINAL_GRACE_MS = 2500;
let toolTurnFinalTimer: ReturnType<typeof setTimeout> | null = null;

function clearToolTurnFinalTimer() {
  if (toolTurnFinalTimer) clearTimeout(toolTurnFinalTimer);
  toolTurnFinalTimer = null;
}

function armToolTurnFinalFallback(status: string | undefined) {
  if (!["success", "failed", "timeout", "needs_clarification"].includes(status || "")) return;
  clearToolTurnFinalTimer();
  toolTurnFinalTimer = setTimeout(() => {
    useChatStore.getState().completeToolTurnFallback();
    toolTurnFinalTimer = null;
  }, TOOL_TURN_FINAL_GRACE_MS);
}

export const useWsStore = create<WsState>((set, get) => ({
  status: "disconnected",
  sessionId: null,
  activeRuntime: "harness",
  client: null,

  connect: (token?: string) => {
    if (!token) {
      console.error("WebSocket connect requires a valid auth token");
      set({ status: "failed" });
      return;
    }
    const existing = get().client;
    if (existing) existing.disconnect();

    const agentRuntime = getActiveAgentRuntime();
    const client = new CompanionWsClient(WS_URL);

    // Status changes
    client.on("_status", (data) => {
      const newStatus = data.status as WsStatus;
      set({ status: newStatus });
      // Reset streaming state on disconnect to unblock the send button
      if (newStatus === "disconnected" || newStatus === "reconnecting" || newStatus === "failed") {
        clearToolTurnFinalTimer();
        useChatStore.getState().resetStreaming();
      }
    });

    // Connected
    client.on("connected", (data) => {
      set({
        sessionId: data.session_id,
        status: "connected",
        activeRuntime: data.agent_runtime || agentRuntime,
      });
    });

    // Trace ID
    client.on("trace", (data) => {
      useChatStore.getState().startAssistantMessage(data.trace_id);
    });

    // Risk alert
    client.on("risk_alert", (data) => {
      useChatStore.getState().setRiskAlert(data.trace_id, data.level, data.message);
    });

    // First reply
    client.on("first_reply", (data) => {
      useChatStore.getState().setFirstReply(data.trace_id, data.text, data.ttft_ms);
    });

    // Delta
    client.on("delta", (data) => {
      useChatStore.getState().appendDelta(data.trace_id, data.text);
    });

    // Tool status
    client.on("tool_status", (data) => {
      useChatStore.getState().setToolStatus(data.trace_id, data.tool, data.status);
    });

    // Tool result — may carry clarify candidates for CareTask UI
    client.on("tool_result", (data) => {
      const payload = data.data || {};
      useChatStore.getState().setToolResult({
        traceId: data.trace_id,
        tool: data.tool,
        status: data.status,
        text: data.text,
        action: data.action || payload.action,
        data: payload,
        candidates: data.candidates || payload.candidates,
        clarifyVerb: payload.clarify_verb || data.clarify_verb,
      });
      armToolTurnFinalFallback(data.status);
    });

    // Final
    client.on("final", (data) => {
      clearToolTurnFinalTimer();
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
      clearToolTurnFinalTimer();
      useChatStore.getState().setError(data.trace_id, data.message);
    });

    client.on("cancelled", (data) => {
      clearToolTurnFinalTimer();
      useChatStore.getState().acknowledgeCancellation(data.trace_id);
    });

    set({ client, status: "connecting" });
    client.connect(token, undefined, undefined, agentRuntime);
  },

  disconnect: () => {
    clearToolTurnFinalTimer();
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

  stopGeneration: () => {
    clearToolTurnFinalTimer();
    const { client } = get();
    const traceId = useChatStore.getState().currentTraceId;
    if (client && traceId) client.stopGeneration(traceId);
  },
}));
