"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useChatStore } from "@/stores/chatStore";
import { useWsStore } from "@/stores/wsStore";
import { useAuthStore } from "@/stores/authStore";
import {
  AGENT_RUNTIME_OPTIONS,
  useAgentRuntimeStore,
} from "@/stores/agentRuntimeStore";
import MessageBubble from "./MessageBubble";
import Sidebar from "./Sidebar";

export default function ChatWindow() {
  const [input, setInput] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const wsStatus = useWsStore((s) => s.status);
  const connect = useWsStore((s) => s.connect);
  const sendMessage = useWsStore((s) => s.sendMessage);
  const token = useAuthStore((s) => s.token);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const agentRuntime = useAgentRuntimeStore((s) => s.runtime);
  const setAgentRuntime = useAgentRuntimeStore((s) => s.setRuntime);
  const activeRuntime = useWsStore((s) => s.activeRuntime);
  const disconnect = useWsStore((s) => s.disconnect);
  const router = useRouter();

  useEffect(() => {
    if (!token) {
      router.push("/login");
      return;
    }
    connect(token);
    return () => {
      useWsStore.getState().disconnect();
    };
  }, [connect, token, router]);

  const handleRuntimeChange = (next: "harness" | "pi_experimental") => {
    if (next === agentRuntime) return;
    setAgentRuntime(next);
    if (token) {
      disconnect();
      connect(token);
    }
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const statusDot =
    wsStatus === "connected"
      ? "bg-green-400"
      : wsStatus === "failed"
      ? "bg-red-400"
      : "bg-gray-400";

  const statusLabel: Record<string, string> = {
    connected: "已连接",
    connecting: "连接中...",
    reconnecting: "重连中...",
    disconnected: "未连接",
    failed: "连接失败",
  };

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <Sidebar isOpen={sidebarOpen} onToggle={() => setSidebarOpen(!sidebarOpen)} />

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col bg-white">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 bg-white px-5 py-3">
          <div className="flex items-center gap-3">
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 transition hover:bg-gray-100"
              >
                ☰
              </button>
            )}
            {sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(false)}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 transition hover:bg-gray-100"
              >
                ◧
              </button>
            )}
            <div className="flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold text-gray-800 transition hover:bg-gray-100">
              AI Companion
              <span className="text-[10px] text-gray-400">▾</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-[11px] text-gray-500">
              <span>运行时</span>
              <select
                value={agentRuntime}
                onChange={(e) =>
                  handleRuntimeChange(
                    e.target.value as "harness" | "pi_experimental"
                  )
                }
                className="rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] text-gray-700 outline-none focus:border-indigo-400"
                title={
                  AGENT_RUNTIME_OPTIONS.find((o) => o.id === agentRuntime)
                    ?.description
                }
              >
                {AGENT_RUNTIME_OPTIONS.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            {activeRuntime === "pi_experimental" && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                实验
              </span>
            )}
            <span className={`h-1.5 w-1.5 rounded-full ${statusDot}`} />
            <span className="text-[11px] text-gray-500">
              {statusLabel[wsStatus]}
            </span>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center px-4">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-purple-500 text-[22px] font-bold text-white shadow-lg shadow-indigo-500/30">
                C
              </div>
              <h2 className="mb-1.5 text-[22px] font-semibold text-gray-800">
                你好，有什么可以帮你的？
              </h2>
              <p className="text-sm text-gray-400">
                我是你的 AI Companion，随时准备聊天
              </p>
              <div className="mt-8 grid w-full max-w-[500px] grid-cols-2 gap-2.5">
                {[
                  { title: "聊聊心情", desc: "说说今天过得怎么样" },
                  { title: "查天气", desc: "帮你看看明天的天气" },
                  { title: "帮我计算", desc: "解决一道数学题" },
                  { title: "搜索信息", desc: "帮你查找相关资料" },
                ].map((item) => (
                  <button
                    key={item.title}
                    onClick={() => {
                      if (wsStatus === "connected") {
                        sendMessage(item.desc);
                      }
                    }}
                    className="rounded-xl border border-gray-200 bg-white p-3.5 text-left transition hover:border-indigo-200 hover:bg-indigo-50/50"
                  >
                    <div className="text-[13px] font-medium text-gray-700">
                      {item.title}
                    </div>
                    <div className="mt-0.5 text-[11px] text-gray-400">
                      {item.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <MessageBubble key={msg.id} message={msg} />
              ))}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Input */}
        <div className="bg-white px-4 pb-4 pt-3">
          <div className="relative mx-auto max-w-3xl">
            <textarea
              ref={textareaRef}
              className="w-full resize-none rounded-2xl border border-gray-300 bg-white py-3.5 pl-4.5 pr-14 text-sm leading-relaxed outline-none transition focus:border-indigo-500 focus:shadow-[0_0_0_2px_rgba(99,102,241,0.15)]"
              rows={1}
              placeholder={
                wsStatus === "connected"
                  ? "给 AI Companion 发消息..."
                  : "等待连接..."
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
              className={`absolute bottom-2.5 right-2.5 flex h-8 w-8 items-center justify-center rounded-[10px] text-sm text-white transition active:scale-95 ${
                input.trim() && !isStreaming && wsStatus === "connected"
                  ? "bg-indigo-500 hover:bg-indigo-600"
                  : "cursor-default bg-gray-300"
              }`}
            >
              ↑
            </button>
          </div>
          <p className="mt-2 text-center text-[11px] text-gray-400">
            AI Companion 可能会犯错，重要信息请核实
          </p>
        </div>
      </div>
    </div>
  );
}
