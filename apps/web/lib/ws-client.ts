type MessageHandler = (data: any) => void;

export type AgentRuntimeId = "harness" | "pi_experimental";

export class CompanionWsClient {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: Map<string, MessageHandler[]> = new Map();
  private reconnectAttempts = 0;
  private maxRetries = 10;
  private retryIntervals = [1000, 2000, 5000, 10000, 30000];
  private shouldReconnect = true;
  private token: string = "";
  private sessionId: string | null = null;
  private lastMsgId: string | null = null;
  private agentRuntime: AgentRuntimeId = "harness";

  constructor(baseUrl: string) {
    this.url = baseUrl;
  }

  connect(
    token: string,
    sessionId?: string,
    lastMsgId?: string,
    agentRuntime: AgentRuntimeId = "harness",
  ) {
    this.token = token;
    this.sessionId = sessionId || null;
    this.lastMsgId = lastMsgId || null;
    this.agentRuntime = agentRuntime;
    this.shouldReconnect = true;
    this._doConnect();
  }

  private _doConnect() {
    // Connect without token in URL — auth happens via first message.
    // Accept base origin (ws://host:port) or a full path already ending in /ws/chat.
    const base = this.url.replace(/\/+$/, "");
    const endpoint = base.endsWith("/ws/chat") ? base : `${base}/ws/chat`;
    this.ws = new WebSocket(endpoint);

    this.ws.onopen = () => {
      // Send auth as first message instead of URL query param
      this._sendRaw({
        type: "auth",
        token: this.token,
        session_id: this.sessionId,
        agent_runtime: this.agentRuntime,
      });
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "connected") {
          this.reconnectAttempts = 0;
        }
        this._emit(data.type, data);
        this._emit("_any", data);
      } catch (e) {
        console.error("Failed to parse WS message:", e);
      }
    };

    this.ws.onclose = () => {
      this._emit("_status", { status: "disconnected" });
      if (this.shouldReconnect) {
        this._reconnect();
      }
    };

    this.ws.onerror = (err) => {
      console.error("WebSocket error:", err);
    };
  }

  private _reconnect() {
    if (this.reconnectAttempts >= this.maxRetries) {
      this._emit("_status", { status: "failed" });
      return;
    }
    const delay = this.retryIntervals[
      Math.min(this.reconnectAttempts, this.retryIntervals.length - 1)
    ];
    this._emit("_status", { status: "reconnecting" });
    setTimeout(() => {
      this.reconnectAttempts++;
      this._doConnect();
    }, delay);
  }

  disconnect() {
    this.shouldReconnect = false;
    this.handlers.clear();
    this.ws?.close();
    this.ws = null;
  }

  private _sendRaw(data: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  send(data: object) {
    this._sendRaw(data);
  }

  sendMessage(message: string) {
    this.send({ type: "user_message", message, session_id: this.sessionId });
  }

  stopGeneration(traceId: string) {
    this.send({ type: "stop_generation", trace_id: traceId });
  }

  on(type: string, handler: MessageHandler) {
    if (!this.handlers.has(type)) this.handlers.set(type, []);
    this.handlers.get(type)!.push(handler);
  }

  off(type: string, handler: MessageHandler) {
    const list = this.handlers.get(type);
    if (list) {
      this.handlers.set(type, list.filter((h) => h !== handler));
    }
  }

  private _emit(type: string, data: any) {
    this.handlers.get(type)?.forEach((h) => h(data));
  }

  setSessionId(id: string) {
    this.sessionId = id;
  }

  setLastMsgId(id: string) {
    this.lastMsgId = id;
  }

  setAgentRuntime(runtime: AgentRuntimeId) {
    this.agentRuntime = runtime;
  }
}
