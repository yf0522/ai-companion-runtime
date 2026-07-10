"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, BellRing, CalendarCheck2, PhoneCall, ShieldAlert } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { useWsStore } from "@/stores/wsStore";
import { useAuthStore } from "@/stores/authStore";
import { useAgentRuntimeStore } from "@/stores/agentRuntimeStore";
import CompanionSignal from "./CompanionSignal";
import MessageBubble from "./MessageBubble";
import type { CareTaskCandidate } from "./CareTaskClarifyCard";

const clarifyVerbLabels: Record<string, string> = {
  取消: "取消任务",
  完成: "完成任务",
};

const quickActions = [
  { title: "看看今天的安排", message: "我今天需要做什么", icon: CalendarCheck2 },
  { title: "设置吃药提醒", message: "提醒我晚上八点吃药", icon: BellRing },
  { title: "请家人联系我", message: "我想让家人知道我需要帮助", icon: PhoneCall },
  { title: "帮我判断是否诈骗", message: "有人让我转账，我不确定", icon: ShieldAlert },
];

export default function ChatWindow() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messages = useChatStore((state) => state.messages);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const wsStatus = useWsStore((state) => state.status);
  const connect = useWsStore((state) => state.connect);
  const sendMessage = useWsStore((state) => state.sendMessage);
  const token = useAuthStore((state) => state.token);
  const authHydrated = useAuthStore((state) => state.hydrated);
  const setAuthHydrated = useAuthStore((state) => state.setHydrated);
  const runtimeHydrated = useAgentRuntimeStore((state) => state.hydrated);
  const hydrateRuntime = useAgentRuntimeStore((state) => state.hydrate);
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
    return () => useWsStore.getState().disconnect();
  }, [authHydrated, runtimeHydrated, connect, token, router]);

  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    messagesEndRef.current?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth" });
  }, [messages]);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
  }, [input]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming || wsStatus !== "connected") return;
    sendMessage(trimmed);
    setInput("");
  };

  const handleClarifySelect = (candidate: CareTaskCandidate, verb: string) => {
    if (isStreaming || wsStatus !== "connected") return;
    const action = clarifyVerbLabels[verb] || "选择任务";
    sendMessage(`${action} ${candidate.title} id=${candidate.id}`);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface shadow-panel">
      <div className="border-b border-border bg-[#f8fbfa] px-4 py-4 sm:px-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="eyebrow">Companion Signal</div>
            <p className="mt-1 text-base font-semibold text-ink">先说一件最需要确认的事，我会一步一步陪你处理。</p>
          </div>
          <CompanionSignal status={wsStatus} />
        </div>
      </div>

      <div className="min-h-[430px] max-h-[calc(100vh-340px)] overflow-y-auto bg-surface">
        {messages.length === 0 ? (
          <div className="mx-auto flex min-h-[430px] max-w-4xl flex-col justify-center px-4 py-10 sm:px-6">
            <div className="max-w-2xl">
              <div className="eyebrow">今天的下一步</div>
              <h2 className="mt-2 text-[26px] font-bold leading-tight text-ink sm:text-[32px]">现在想先处理哪件事？</h2>
              <p className="mt-3 text-lg leading-8 text-muted">可以直接说身体不舒服、提醒、联系家人，或者把可疑电话和转账要求告诉我。</p>
            </div>
            <div className="mt-7 grid gap-3 sm:grid-cols-2">
              {quickActions.map(({ title, message, icon: Icon }) => (
                <button
                  key={title}
                  type="button"
                  disabled={wsStatus !== "connected"}
                  onClick={() => sendMessage(message)}
                  className="group flex min-h-[84px] items-center gap-4 rounded-lg border border-border bg-surface p-4 text-left transition hover:border-primary hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary-strong group-hover:bg-surface">
                    <Icon size={22} aria-hidden="true" />
                  </span>
                  <span>
                    <strong className="block text-base text-ink">{title}</strong>
                    <span className="mt-1 block text-sm leading-6 text-muted">“{message}”</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                isStreaming={isStreaming}
                onClarifySelect={handleClarifySelect}
              />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      <div className="border-t border-border bg-[#f8fbfa] p-3 sm:p-4">
        <div className="chat-composer relative mx-auto max-w-3xl">
          <label htmlFor="elder-message" className="sr-only">输入给陪伴助手的消息</label>
          <textarea
            id="elder-message"
            ref={textareaRef}
            className="w-full resize-none rounded-lg bg-transparent py-3.5 pl-4 pr-16 text-lg leading-relaxed text-ink outline-none"
            rows={1}
            placeholder={wsStatus === "connected" ? "说说现在最想确认的事..." : "连接恢复后可以继续对话"}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={wsStatus !== "connected"}
            style={{ minHeight: "56px", maxHeight: "200px" }}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={!input.trim() || isStreaming || wsStatus !== "connected"}
            aria-label="发送消息"
            className="absolute bottom-1.5 right-1.5 flex h-11 w-11 items-center justify-center rounded-md bg-primary text-white transition hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-status-offline"
          >
            <ArrowUp size={21} aria-hidden="true" />
          </button>
        </div>
        <p className="mt-2 text-center text-sm leading-6 text-muted">涉及急救、转账或用药变更时，请同时联系家人或专业人员。</p>
      </div>
    </section>
  );
}
