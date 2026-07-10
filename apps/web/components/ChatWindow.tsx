"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useChatStore } from "@/stores/chatStore";
import { useWsStore } from "@/stores/wsStore";
import { useAuthStore } from "@/stores/authStore";
import { useAgentRuntimeStore } from "@/stores/agentRuntimeStore";
import MessageBubble from "./MessageBubble";
import type { CareTaskCandidate } from "./CareTaskClarifyCard";

const clarifyVerbLabels: Record<string, string> = {
  取消: "取消任务",
  完成: "完成任务",
};

const statusDots: Record<string, string> = {
  connected: "bg-status-success",
  failed: "bg-status-critical",
};

const statusLabel: Record<string, string> = {
  connected: "已连接",
  connecting: "连接中...",
  reconnecting: "重连中...",
  disconnected: "未连接",
  failed: "连接失败",
};

export default function ChatWindow() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const wsStatus = useWsStore((s) => s.status);
  const connect = useWsStore((s) => s.connect);
  const sendMessage = useWsStore((s) => s.sendMessage);
  const token = useAuthStore((s) => s.token);
  const authHydrated = useAuthStore((s) => s.hydrated);
  const setAuthHydrated = useAuthStore((s) => s.setHydrated);
  const runtimeHydrated = useAgentRuntimeStore((s) => s.hydrated);
  const hydrateRuntime = useAgentRuntimeStore((s) => s.hydrate);
  const router = useRouter();

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setAuthHydrated();
      return;
    }
    void Promise.resolve(useAuthStore.persist.rehydrate()).finally(setAuthHydrated);
  }, [setAuthHydrated]);

  useEffect(() => {
    hydrateRuntime();
  }, [hydrateRuntime]);

  useEffect(() => {
    if (!authHydrated) return;
    if (!runtimeHydrated) return;
    if (!token) {
      router.push("/login");
      return;
    }
    connect(token);
    return () => {
      useWsStore.getState().disconnect();
    };
  }, [authHydrated, runtimeHydrated, connect, token, router]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, [input]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;
    sendMessage(trimmed);
    setInput("");
  };

  const handleClarifySelect = (candidate: CareTaskCandidate, verb: string) => {
    if (isStreaming || wsStatus !== "connected") return;
    const action = clarifyVerbLabels[verb] || "选择任务";
    const text = `${action} ${candidate.title} id=${candidate.id}`;
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const statusDot = statusDots[wsStatus] || "bg-status-offline";

  return (
    <div className="min-h-[calc(100vh-220px)] rounded-md border border-border bg-surface">
      <div className="flex min-h-[calc(100vh-220px)] min-w-0 flex-1 flex-col">
        <div className="flex flex-col gap-2 border-b border-border bg-surface px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-md bg-primary-soft px-3 py-2 text-sm font-semibold text-primary-strong">
              陪伴对话
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className={`h-1.5 w-1.5 rounded-full ${statusDot}`} />
            <span className="text-sm text-muted" aria-live="polite">
              {statusLabel[wsStatus]}
            </span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center px-4 py-12">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-[22px] font-bold text-white">
                C
              </div>
              <h2 className="mb-1.5 text-[22px] font-semibold text-ink">
                今天想先确认哪件事？
              </h2>
              <p className="text-base text-muted">
                可以说提醒、身体不舒服、担心被骗，或想联系家人。
              </p>
              <div className="mt-8 grid w-full max-w-[500px] grid-cols-2 gap-2.5">
                {[
                  { title: "确认今日事项", desc: "我今天需要做什么" },
                  { title: "设置提醒", desc: "提醒我晚上八点吃药" },
                  { title: "联系家人", desc: "我想让家人知道我需要帮助" },
                  { title: "说明风险", desc: "有人让我转账，我不确定" },
                ].map((item) => (
                  <button
                    key={item.title}
                    onClick={() => {
                      if (wsStatus === "connected") {
                        sendMessage(item.desc);
                      }
                    }}
                    className="min-h-11 rounded-md border border-border bg-surface p-3.5 text-left transition hover:border-primary hover:bg-primary-soft"
                  >
                    <div className="text-base font-medium text-ink">
                      {item.title}
                    </div>
                    <div className="mt-0.5 text-sm text-muted">
                      {item.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isStreaming={isStreaming}
                  onClarifySelect={handleClarifySelect}
                />
              ))}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        <div className="bg-surface px-4 pb-4 pt-3">
          <div className="relative mx-auto max-w-3xl">
            <label htmlFor="elder-message" className="sr-only">
              输入给陪伴助手的消息
            </label>
            <textarea
              id="elder-message"
              ref={textareaRef}
              className="w-full resize-none rounded-md border border-border bg-surface py-3.5 pl-4 pr-16 text-lg leading-relaxed outline-none transition focus:border-primary"
              rows={1}
              placeholder={
                wsStatus === "connected"
                  ? "输入想确认的事项..."
                  : "连接后可以发送消息"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={wsStatus !== "connected"}
              style={{ minHeight: "52px", maxHeight: "200px" }}
            />
            <button
              onClick={handleSend}
              disabled={
                !input.trim() || isStreaming || wsStatus !== "connected"
              }
              aria-label="发送消息"
              className={`absolute bottom-2 right-2 flex h-11 w-11 items-center justify-center rounded-md text-lg text-white transition active:scale-95 ${
                input.trim() && !isStreaming && wsStatus === "connected"
                  ? "bg-primary hover:bg-primary-hover"
                  : "cursor-default bg-gray-300"
              }`}
            >
              ↑
            </button>
          </div>
          <p className="mt-2 text-center text-sm text-muted">
            重要健康和资金事项请与家人或专业人员确认。
          </p>
        </div>
      </div>
    </div>
  );
}
