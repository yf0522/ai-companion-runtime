"use client";

import { useRef, useState } from "react";
import {
  ChatComposer,
  ChatComposerInput,
  ChatDictationButton,
  type ChatComposerInputHandle,
  useChatDictation,
} from "@astryxdesign/core/Chat";
import { CircleStop, RotateCcw, SendHorizontal } from "lucide-react";
import styles from "./ElderProduct.module.css";

type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting" | "failed";

const connectionCopy: Record<ConnectionStatus, string> = {
  disconnected: "尚未连接，草稿会保留在本页",
  connecting: "正在连接，草稿已保留，不会自动发送",
  connected: "连接正常，由你确认后才会发送",
  reconnecting: "正在恢复连接，草稿已保留，不会自动发送",
  failed: "暂时无法连接，草稿已保留",
};

export default function CompanionActionDock({
  value,
  onChange,
  onSubmit,
  onStop,
  onReconnect,
  isStreaming,
  status,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  onStop: () => void;
  onReconnect: () => void;
  isStreaming: boolean;
  status: ConnectionStatus;
}) {
  const inputRef = useRef<ChatComposerInputHandle>(null);
  const [dictationError, setDictationError] = useState<string | null>(null);
  const dictation = useChatDictation({
    lang: "zh-CN",
    inputRef,
    onError: () => setDictationError("语音输入没有启动，可以继续打字。"),
  });
  const canSend = status === "connected" && !isStreaming && value.trim().length > 0;

  function handleSubmit(submitted: string) {
    const draft = submitted.trim();
    if (!draft) return;
    if (status !== "connected" || isStreaming) {
      // ChatComposerInput clears its DOM after Enter. Restore the controlled
      // draft on the next frame when transport is unavailable.
      window.requestAnimationFrame(() => onChange(submitted));
      return;
    }
    onSubmit(draft);
  }

  return (
    <div className={styles.actionDock}>
      <ChatComposer
        className={styles.composer}
        density="compact"
        value={value}
        onChange={onChange}
        onSubmit={handleSubmit}
        isStopShown={isStreaming}
        onStop={onStop}
        placeholder="说说现在最需要确认的事…"
        input={(
          <ChatComposerInput
            handleRef={inputRef}
            value={value}
            onChange={onChange}
            onSubmit={handleSubmit}
            label="输入给陪伴助手的消息"
            placeholder="说说现在最需要确认的事…"
            maxRows={4}
            pasteAsToken={false}
          />
        )}
        sendActions={(
          <ChatDictationButton
            className={styles.dictationButton}
            dictation={dictation}
            label={dictation.isListening ? "停止语音输入" : "开始语音输入"}
          />
        )}
        sendButton={isStreaming ? (
          <button type="button" className={styles.stopButton} onClick={onStop} aria-label="停止回复">
            <CircleStop size={20} aria-hidden="true" />
          </button>
        ) : (
          <button type="button" className={styles.sendButton} disabled={!canSend} onClick={() => handleSubmit(value)} aria-label="发送消息">
            <SendHorizontal size={20} aria-hidden="true" />
          </button>
        )}
      />

      <div className={styles.dockStatus} data-state={status} role="status">
        <span>{connectionCopy[status]}</span>
        {status === "failed" && (
          <button type="button" onClick={onReconnect}><RotateCcw size={15} aria-hidden="true" />重新连接</button>
        )}
        <a href="/elder/help">需要帮助</a>
      </div>
      {!dictation.isSupported && (
        <p className={styles.dictationHint}>当前浏览器不支持语音输入，可以继续打字</p>
      )}
      {dictationError && <p className={styles.dictationHint}>{dictationError}</p>}
    </div>
  );
}
