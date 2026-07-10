"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { ChatComposer, ChatComposerInput, ChatLayout, ChatMessageList } from "@astryxdesign/core/Chat";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { BellRing, CalendarCheck2, HeartHandshake, PhoneCall, ShieldAlert } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { useWsStore } from "@/stores/wsStore";
import { useAuthStore } from "@/stores/authStore";
import { AGENT_RUNTIME_OPTIONS, useAgentRuntimeStore } from "@/stores/agentRuntimeStore";
import CompanionSignal from "./CompanionSignal";
import MessageBubble from "./MessageBubble";
import SignalField from "./SignalField";
import type { CareTaskCandidate } from "./CareTaskClarifyCard";

const clarifyVerbLabels: Record<string, string> = { 取消: "取消任务", 完成: "完成任务" };
const quickActions = [
  { title: "看看今天的安排", message: "我今天需要做什么", icon: CalendarCheck2 },
  { title: "设置吃药提醒", message: "提醒我晚上八点吃药", icon: BellRing },
  { title: "请家人联系我", message: "我想让家人知道我需要帮助", icon: PhoneCall },
  { title: "帮我判断是否诈骗", message: "有人让我转账，我不确定", icon: ShieldAlert },
];

export default function ChatWindow() {
  const [input, setInput] = useState("");
  const chatLayoutRef = useRef<HTMLDivElement>(null);
  const messages = useChatStore((state) => state.messages);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const wsStatus = useWsStore((state) => state.status);
  const connect = useWsStore((state) => state.connect);
  const sendMessage = useWsStore((state) => state.sendMessage);
  const stopGeneration = useWsStore((state) => state.stopGeneration);
  const token = useAuthStore((state) => state.token);
  const authHydrated = useAuthStore((state) => state.hydrated);
  const setAuthHydrated = useAuthStore((state) => state.setHydrated);
  const runtime = useAgentRuntimeStore((state) => state.runtime);
  const runtimeHydrated = useAgentRuntimeStore((state) => state.hydrated);
  const hydrateRuntime = useAgentRuntimeStore((state) => state.hydrate);
  const router = useRouter();

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) { setAuthHydrated(); return; }
    void Promise.resolve(useAuthStore.persist.rehydrate()).finally(setAuthHydrated);
  }, [setAuthHydrated]);
  useEffect(() => { hydrateRuntime(); }, [hydrateRuntime]);
  useEffect(() => {
    if (!authHydrated || !runtimeHydrated) return;
    if (!token) { router.push("/login"); return; }
    connect(token);
    return () => useWsStore.getState().disconnect();
  }, [authHydrated, runtimeHydrated, connect, token, router]);
  useEffect(() => {
    if (messages.length > 0) return;
    const resetEmptyStateScroll = () => {
      if (chatLayoutRef.current) chatLayoutRef.current.scrollTop = 0;
    };
    const frame = window.requestAnimationFrame(() => window.requestAnimationFrame(resetEmptyStateScroll));
    return () => window.cancelAnimationFrame(frame);
  }, [messages.length, wsStatus]);

  function handleSend(value = input) {
    const trimmed = value.trim();
    if (!trimmed || isStreaming || wsStatus !== "connected") return;
    sendMessage(trimmed);
    setInput("");
  }

  function handleClarifySelect(candidate: CareTaskCandidate, verb: string) {
    if (isStreaming || wsStatus !== "connected") return;
    const action = clarifyVerbLabels[verb] || "选择任务";
    sendMessage(`${action} ${candidate.title} id=${candidate.id}`);
  }

  const runtimeLabel = AGENT_RUNTIME_OPTIONS.find((option) => option.id === runtime)?.label || "标准 Harness";
  const emptyState = (
    <div className="companion-empty">
      <SignalField />
      <div className="companion-empty-content">
        <div className="companion-presence"><HeartHandshake size={26} /></div>
        <h2>现在想先处理哪件事？</h2>
        <p className="companion-empty-copy">你可以直接说身体不舒服、提醒、联系家人，或把可疑电话和转账要求告诉我。</p>
        <div className="companion-prompts">
          {quickActions.map(({ title, message, icon: PromptIcon }) => (
            <button key={title} type="button" className="companion-prompt" disabled={wsStatus !== "connected"} onClick={() => handleSend(message)}>
              <PromptIcon size={21} />
              <span><strong style={{ display: "block" }}>{title}</strong><small style={{ display: "block", marginTop: 6, color: "var(--companion-muted)", lineHeight: 1.5 }}>“{message}”</small></span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <section className="companion-workspace">
      <div className="companion-stage">
        <div className="companion-stage-header">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}><CompanionSignal status={wsStatus} /><Badge label={runtimeLabel} variant="neutral" /></div>
          <Button label="今日事项" href="/elder/today" variant="ghost" size="md" icon={<Icon icon={CalendarCheck2} size="sm" />} />
        </div>
        <div className="companion-chat">
          <ChatLayout
            ref={chatLayoutRef}
            density="spacious"
            emptyState={messages.length === 0 ? emptyState : undefined}
            composer={
              <ChatComposer
                value={input}
                onChange={setInput}
                onSubmit={handleSend}
                isStopShown={isStreaming}
                onStop={stopGeneration}
                isDisabled={wsStatus !== "connected"}
                density="spacious"
                placeholder={wsStatus === "connected" ? "说说现在最需要确认的事…" : "连接恢复后可以继续对话"}
                input={<ChatComposerInput value={input} onChange={setInput} onSubmit={handleSend} label="输入给陪伴助手的消息" isDisabled={wsStatus !== "connected"} placeholder={wsStatus === "connected" ? "说说现在最需要确认的事…" : "连接恢复后可以继续对话"} maxRows={6} />}
                headerContext={<Text type="supporting" color="secondary">{isStreaming ? "Companion 正在回应" : "风险、记忆与工具会自动检查"}</Text>}
                footerActions={<Badge label="不会替代急救、医生或银行" variant="neutral" />}
                status={wsStatus === "failed" ? { type: "error", message: "陪伴服务暂时不可用，请联系家人或稍后重试。" } : undefined}
              />
            }
          >
            {messages.length > 0 ? <ChatMessageList>{messages.map((message) => <MessageBubble key={message.id} message={message} isStreaming={isStreaming} onClarifySelect={handleClarifySelect} />)}</ChatMessageList> : null}
          </ChatLayout>
        </div>
      </div>
    </section>
  );
}
