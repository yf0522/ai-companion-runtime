"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChatLayout, ChatMessageList } from "@astryxdesign/core/Chat";
import { BellRing, CalendarCheck2, HeartHandshake, PhoneCall, ShieldAlert, ShieldCheck } from "lucide-react";
import { fetchCareTasks, fetchContacts, type VerifiedContact } from "@/lib/api-client";
import { useChatStore } from "@/stores/chatStore";
import { useWsStore } from "@/stores/wsStore";
import { useAuthStore } from "@/stores/authStore";
import CompanionSignal from "./CompanionSignal";
import MessageBubble from "./MessageBubble";
import CompanionActionDock from "./elder/CompanionActionDock";
import styles from "./elder/ElderProduct.module.css";
import type { CareTaskCandidate } from "./CareTaskClarifyCard";

const clarifyVerbLabels: Record<string, string> = { 取消: "取消任务", 完成: "完成任务" };

function phoneHref(value: string): string {
  return `tel:${value.replace(/[^+\d]/g, "")}`;
}

export default function ChatWindow() {
  const [input, setInput] = useState("");
  const [chatReady, setChatReady] = useState(false);
  const [nextTaskTitle, setNextTaskTitle] = useState<string | null>(null);
  const [directContact, setDirectContact] = useState<VerifiedContact | null>(null);
  const chatLayoutRef = useRef<HTMLDivElement>(null);
  const messages = useChatStore((state) => state.messages);
  const activateUser = useChatStore((state) => state.activateUser);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const wsStatus = useWsStore((state) => state.status);
  const connect = useWsStore((state) => state.connect);
  const sendMessage = useWsStore((state) => state.sendMessage);
  const stopGeneration = useWsStore((state) => state.stopGeneration);
  const token = useAuthStore((state) => state.token);
  const userId = useAuthStore((state) => state.userId);
  const authHydrated = useAuthStore((state) => state.hydrated);
  const setAuthHydrated = useAuthStore((state) => state.setHydrated);
  const router = useRouter();

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) { setAuthHydrated(); return; }
    void Promise.resolve(useAuthStore.persist.rehydrate()).finally(setAuthHydrated);
  }, [setAuthHydrated]);

  useEffect(() => {
    if (!authHydrated) return;
    let active = true;
    setChatReady(false);
    void Promise.resolve(useChatStore.persist.rehydrate()).finally(() => {
      if (!active) return;
      activateUser(userId);
      setChatReady(true);
    });
    return () => { active = false; };
  }, [activateUser, authHydrated, userId]);

  useEffect(() => {
    if (!authHydrated || !chatReady) return;
    if (!token) { router.push("/login"); return; }
    connect(token);
    return () => useWsStore.getState().disconnect();
  }, [authHydrated, chatReady, connect, token, router]);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.allSettled([
      fetchCareTasks({ scope: "today", limit: 1 }),
      fetchContacts(),
    ]).then(([tasksResult, contactsResult]) => {
      if (!active) return;
      if (tasksResult.status === "fulfilled") {
        setNextTaskTitle(tasksResult.value[0]?.title || null);
      }
      if (contactsResult.status === "fulfilled") {
        const contact = contactsResult.value.items.find((item) =>
          item.verification_status === "verified" &&
          item.available !== false &&
          ["phone", "sms"].includes(item.channel),
        );
        setDirectContact(contact || null);
      }
    });
    return () => { active = false; };
  }, [token]);

  function handleSend(value = input) {
    const trimmed = value.trim();
    if (!trimmed || isStreaming || wsStatus !== "connected") return;
    sendMessage(trimmed);
    setInput("");
  }

  function handleReconnect() {
    if (!token) return;
    useWsStore.getState().disconnect();
    connect(token);
  }

  function handleClarifySelect(candidate: CareTaskCandidate, verb: string) {
    if (isStreaming || wsStatus !== "connected") return;
    const action = clarifyVerbLabels[verb] || "选择任务";
    sendMessage(`${action} ${candidate.title} id=${candidate.id}`);
  }

  const quickActions = [
    nextTaskTitle
      ? { title: `看看“${nextTaskTitle}”`, message: "请列出今天的照护任务", icon: CalendarCheck2 }
      : { title: "看看今天的安排", message: "请列出今天的照护任务", icon: CalendarCheck2 },
    { title: "设置吃药提醒", message: "提醒我晚上八点吃药", icon: BellRing },
    { title: "请家人联系我", message: "我想让家人知道我需要帮助", icon: PhoneCall },
    { title: "帮我判断是否诈骗", message: "有人让我转账，我不确定", icon: ShieldAlert },
  ];

  const emptyState = (
    <div className="companion-empty">
      <div className="companion-empty-content">
        <div className="companion-presence" aria-hidden="true"><HeartHandshake size={24} /></div>
        <p className="companion-welcome">我在这里</p>
        <h2>今天想先说哪件事？</h2>
        <p className="companion-empty-copy">身体不舒服、需要提醒、想联系家人，或者遇到可疑电话，都可以直接告诉我。下面的选择只会填入草稿，由你确认发送。</p>
        <div className="companion-prompts">
          {quickActions.map(({ title, message, icon: PromptIcon }) => (
            <button key={title} type="button" className="companion-prompt" onClick={() => setInput(message)}>
              <PromptIcon size={20} aria-hidden="true" />
              <span><strong>{title}</strong><small>“{message}”</small></span>
            </button>
          ))}
        </div>
        {directContact ? (
          <a className="companion-help-link" href={phoneHref(directContact.value)} aria-label={`打电话给${directContact.name}`}>
            直接打电话给{directContact.name}
          </a>
        ) : (
          <a className="companion-help-link" href="/elder/help">现在需要帮助？查看已验证联系人</a>
        )}
      </div>
    </div>
  );

  return (
    <section className="companion-workspace">
      <div className="companion-stage">
        <div className="companion-stage-header">
          <CompanionSignal status={wsStatus} />
          <a className={styles.stageLink} href="/elder/memory"><ShieldCheck size={17} aria-hidden="true" />记忆与隐私</a>
        </div>
        <div className="companion-chat">
          <ChatLayout
            ref={chatLayoutRef}
            density="spacious"
            emptyState={messages.length === 0 ? emptyState : undefined}
            scrollButton={messages.length === 0 ? null : undefined}
            composer={(
              <CompanionActionDock
                value={input}
                onChange={setInput}
                onSubmit={handleSend}
                onStop={stopGeneration}
                onReconnect={handleReconnect}
                isStreaming={isStreaming}
                status={wsStatus}
              />
            )}
          >
            {messages.length > 0 ? (
              <ChatMessageList isStreaming={isStreaming}>
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} isStreaming={isStreaming} onClarifySelect={handleClarifySelect} />
                ))}
              </ChatMessageList>
            ) : null}
          </ChatLayout>
        </div>
      </div>
    </section>
  );
}
