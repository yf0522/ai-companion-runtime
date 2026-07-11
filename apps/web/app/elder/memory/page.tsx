"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, History, Pencil, ShieldCheck, Trash2, X } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  correctMemory,
  decideMemoryConsent,
  deleteMemory,
  fetchMemories,
  type MemoryItem,
  userFacingApiError,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/authStore";
import { useChatStore } from "@/stores/chatStore";
import styles from "@/components/elder/ElderProduct.module.css";
import { memoryCorrectionReceipt } from "./correction-receipt";

const consentLabels: Record<string, string> = {
  pending: "等待你的同意",
  legacy_unverified: "需要你的选择",
  granted: "已同意保留",
  rejected: "不保留",
  expired: "保留期已结束",
};

export default function ElderMemoryPage() {
  const router = useRouter();
  const userId = useAuthStore((state) => state.userId);
  const activateChatUser = useChatStore((state) => state.activateUser);
  const clearMessages = useChatStore((state) => state.clearMessages);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setMemories((await fetchMemories(100)).memories.filter((item) => item.deletion_state !== "deleted"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(userFacingApiError(err, "记忆内容暂时无法加载。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    let active = true;
    void Promise.resolve(useChatStore.persist.rehydrate()).finally(() => {
      if (active) activateChatUser(userId);
    });
    return () => { active = false; };
  }, [activateChatUser, userId]);

  async function handleConsent(memory: MemoryItem, approved: boolean) {
    setBusyId(memory.id);
    setError(null);
    setReceipt(null);
    try {
      const result = await decideMemoryConsent(memory.id, approved);
      setMemories((items) => items.map((item) => item.id === memory.id
        ? {
            ...item,
            consent_status: result.consent_status,
            retrievable: result.consent_status === "granted" && item.retention_status !== "expired",
          }
        : item));
      setReceipt(approved ? "这条记忆已按你的选择保留。" : "这条记忆不会用于长期陪伴。你仍可将它彻底删除。");
    } catch (err) {
      setError(userFacingApiError(err, "同意状态更新失败，原来的选择没有改变。"));
    } finally {
      setBusyId(null);
    }
  }

  function startEditing(memory: MemoryItem) {
    setEditingId(memory.id);
    setEditValue(memory.content);
    setError(null);
    setReceipt(null);
  }

  async function handleCorrection(memory: MemoryItem) {
    const corrected = editValue.trim();
    if (!corrected) return;
    setBusyId(memory.id);
    setError(null);
    try {
      await correctMemory(memory.id, corrected, "本人在记忆中心修改");
      setMemories((items) => items.map((item) => item.id === memory.id
        ? { ...item, content: corrected, correction_state: "corrected" }
        : item));
      setEditingId(null);
      setReceipt(memoryCorrectionReceipt(memory.consent_status, memory.retention_status));
    } catch (err) {
      setError(userFacingApiError(err, "修改失败，原来的内容仍然保留。"));
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(memory: MemoryItem) {
    if (!window.confirm(`确定删除“${memory.content}”吗？删除后不会再用于陪伴。`)) return;
    setBusyId(memory.id);
    setError(null);
    setReceipt(null);
    try {
      await deleteMemory(memory.id);
      setMemories((items) => items.filter((item) => item.id !== memory.id));
      setReceipt("这条记忆已删除，不再用于后续陪伴。" );
    } catch (err) {
      setError(userFacingApiError(err, "删除失败，这条记忆仍然保留。"));
    } finally {
      setBusyId(null);
    }
  }

  function handleClearLocalChat() {
    if (!window.confirm("确定清除这个账号在本机保存的对话记录吗？这个操作不会删除服务端记忆。")) return;
    activateChatUser(userId);
    clearMessages();
    setReceipt("这个账号在本机保存的对话记录已清除。长期记忆没有因此改变。" );
  }

  return (
    <RoleShell role="elder" title="记忆与隐私">
      <div className={`${styles.pageStack} product-grid`}>
        <section className={styles.pageIntro}>
          <div>
            <p>由你决定</p>
            <h2>记忆与隐私</h2>
            <span>查看陪伴助手长期保留的内容，决定是否同意、修改或删除。这里仅对本人账号开放。</span>
          </div>
          <a className={styles.helpAction} href="/elder/companion"><History size={18} aria-hidden="true" />回到陪伴</a>
        </section>

        <StatusBanner tone="info" title="两类记录彼此独立">
          长期记忆由你逐条控制；本机对话记录只保存在这个浏览器，并按登录账号隔离。清除其中一类不会偷偷删除或保留另一类。
        </StatusBanner>
        {receipt && <StatusBanner tone="success" title="更改已确认">{receipt}</StatusBanner>}
        {error && memories.length > 0 && <ErrorState title="更改没有完成" description={error} onRetry={load} />}

        <section className={styles.memorySection} aria-label="长期记忆">
          <div className={styles.memoryHeading}>
            <div><p>长期记忆</p><h2>陪伴助手记住的内容</h2></div>
            <ShieldCheck size={24} aria-hidden="true" />
          </div>

          {loading ? (
            <LoadingState label="正在加载长期记忆" />
          ) : error && memories.length === 0 ? (
            <ErrorState title="长期记忆暂时不可用" description={error} onRetry={load} />
          ) : memories.length === 0 ? (
            <EmptyState title="目前没有可管理的长期记忆" description="没有内容时不会用空白页面暗示已经保存了记忆。新的候选内容需要同意后才会长期使用。" />
          ) : (
            <div className={styles.memoryList}>
              {memories.map((memory) => (
                <article className={styles.memoryCard} key={memory.id}>
                  <div className={styles.memoryMeta}>
                    <span data-state={memory.retention_status === "expired" ? "expired" : memory.consent_status}>{consentLabels[memory.retention_status === "expired" ? "expired" : memory.consent_status] || "状态待确认"}</span>
                    {memory.correction_state === "corrected" && <span>本人已修改</span>}
                  </div>

                  {memory.retention_status === "expired" && (
                    <p className={styles.memoryRetention}>这条内容仍可由你查看、修改或删除，但保留期已结束，不会再用于陪伴。</p>
                  )}

                  {editingId === memory.id ? (
                    <div className={styles.memoryEditor}>
                      <label htmlFor={`memory-${memory.id}`}>修改内容</label>
                      <textarea id={`memory-${memory.id}`} value={editValue} onChange={(event) => setEditValue(event.target.value)} maxLength={500} />
                      <div>
                        <button type="button" disabled={!editValue.trim() || busyId === memory.id} onClick={() => void handleCorrection(memory)}><Check size={17} />保存修改</button>
                        <button type="button" onClick={() => setEditingId(null)}><X size={17} />取消</button>
                      </div>
                    </div>
                  ) : (
                    <p className={styles.memoryContent}>{memory.content}</p>
                  )}

                  <div className={styles.memoryActions}>
                    {memory.retention_status !== "expired" && ["pending", "legacy_unverified"].includes(memory.consent_status) && (
                      <>
                        <button type="button" disabled={busyId === memory.id} onClick={() => void handleConsent(memory, true)}><Check size={17} />同意保留</button>
                        <button type="button" disabled={busyId === memory.id} onClick={() => void handleConsent(memory, false)}><X size={17} />不保留</button>
                      </>
                    )}
                    <button type="button" disabled={busyId === memory.id} onClick={() => startEditing(memory)}><Pencil size={17} />修改内容</button>
                    <button type="button" disabled={busyId === memory.id} onClick={() => void handleDelete(memory)}><Trash2 size={17} />删除记忆</button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className={styles.localRecordPanel}>
          <div><p>本机记录</p><h2>清除这个账号的本机对话</h2><span>只清除当前账号在这个浏览器保存的完整对话，不影响其他账号，也不等于删除上面的长期记忆。</span></div>
          <button type="button" onClick={handleClearLocalChat}><Trash2 size={18} aria-hidden="true" />清除本机对话记录</button>
        </section>
      </div>
    </RoleShell>
  );
}
