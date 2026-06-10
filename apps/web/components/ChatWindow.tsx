"use client";

import { useEffect, useRef, useState } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useWsStore } from "@/stores/wsStore";
import MessageBubble from "./MessageBubble";

export default function ChatWindow() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const wsStatus = useWsStore((s) => s.status);
  const connect = useWsStore((s) => s.connect);
  const sendMessage = useWsStore((s) => s.sendMessage);

  // Auto-connect on mount
  useEffect(() => {
    connect();
    return () => {
      useWsStore.getState().disconnect();
    };
  }, [connect]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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

  const statusColor = {
    connected: "bg-green-400",
    connecting: "bg-yellow-400",
    reconnecting: "bg-yellow-400",
    disconnected: "bg-gray-400",
    failed: "bg-red-400",
  }[wsStatus];

  const statusText = {
    connected: "已连接",
    connecting: "连接中...",
    reconnecting: "重连中...",
    disconnected: "未连接",
    failed: "连接失败",
  }[wsStatus];

  return (
    <div className="flex h-screen flex-col bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-6 py-3">
        <h1 className="text-lg font-semibold text-gray-800">AI Companion</h1>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${statusColor}`} />
          <span className="text-xs text-gray-500">{statusText}</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-gray-400">
              <p className="text-4xl mb-4">👋</p>
              <p className="text-lg">你好，我是你的 AI Companion</p>
              <p className="text-sm mt-1">随便聊聊吧</p>
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t px-6 py-4">
        <div className="flex gap-3">
          <textarea
            className="flex-1 resize-none rounded-xl border border-gray-200 px-4 py-3 text-sm focus:border-blue-400 focus:outline-none"
            rows={1}
            placeholder={wsStatus === "connected" ? "输入消息..." : "等待连接..."}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={wsStatus !== "connected"}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming || wsStatus !== "connected"}
            className="rounded-xl bg-blue-500 px-6 py-3 text-sm font-medium text-white transition hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {isStreaming ? "生成中..." : "发送"}
          </button>
        </div>
      </div>
    </div>
  );
}
