"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Clock3, HeartHandshake } from "lucide-react";
import CareTaskCard from "@/components/CareTaskCard";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  completeCareTask,
  fetchCareTasks,
  mutationInputForTask,
  snoozeCareTask,
  type CareTaskItem,
  userFacingApiError,
} from "@/lib/api-client";
import { isCareTaskActionable, normalizeCareTaskStatus } from "@/lib/care-task-state";
import styles from "@/components/elder/ElderProduct.module.css";

type BusyAction = { id: string; action: "complete" | "snooze" } | null;

export default function ElderTodayPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<CareTaskItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState<BusyAction>(null);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    setError(null);
    setOffline(!navigator.onLine);
    try {
      setTasks(await fetchCareTasks({ include_terminal: true, scope: "today", limit: 100 }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "今日事项加载失败，请稍后重试。"));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
    const updateOnline = () => setOffline(!navigator.onLine);
    window.addEventListener("online", updateOnline);
    window.addEventListener("offline", updateOnline);
    return () => {
      window.removeEventListener("online", updateOnline);
      window.removeEventListener("offline", updateOnline);
    };
  }, [load]);

  async function handleComplete(task: CareTaskItem) {
    setBusy({ id: task.id, action: "complete" });
    setError(null);
    setReceipt(null);
    try {
      await completeCareTask(task.id, mutationInputForTask(task, "elder-task-complete"));
      setReceipt(`“${task.title}”已记录为完成。`);
      await load(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(userFacingApiError(err, "确认失败，这件事项尚未记录为完成。"));
    } finally {
      setBusy(null);
    }
  }

  async function handleSnooze(task: CareTaskItem) {
    setBusy({ id: task.id, action: "snooze" });
    setError(null);
    setReceipt(null);
    try {
      await snoozeCareTask(task.id, {
        ...mutationInputForTask(task, "elder-task-snooze"),
        minutes: 30,
      });
      setReceipt(`“${task.title}”已延后 30 分钟。`);
      await load(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(userFacingApiError(err, "延后失败，原来的提醒时间仍然保留。"));
    } finally {
      setBusy(null);
    }
  }

  const visibleTasks = useMemo(() => tasks
    .filter((task) => ["pending", "due", "snoozed", "missed"].includes(normalizeCareTaskStatus(task.status)))
    .filter(isCareTaskActionable)
    .sort((left, right) => {
      const rank = { due: 0, missed: 1, pending: 2, snoozed: 3, unknown: 4, done: 5, cancelled: 6 };
      return rank[normalizeCareTaskStatus(left.status)] - rank[normalizeCareTaskStatus(right.status)];
    }), [tasks]);

  const summaryTitle = loading
    ? "正在确认今日事项"
    : error && tasks.length === 0
      ? "暂时无法确认今日事项"
      : visibleTasks.length > 0
        ? `有 ${visibleTasks.length} 件事项等待你确认`
        : "当前没有待确认事项";

  return (
    <RoleShell role="elder" title="今日事项">
      <div className={`${styles.pageStack} product-grid`}>
        <section className={styles.pageIntro}>
          <div>
            <p>今天</p>
            <h2>{summaryTitle}</h2>
            <span>完成、延后和求助都是明确动作；只有服务确认成功后，页面才会更新状态。</span>
          </div>
          <a className={styles.helpAction} href="/elder/help"><HeartHandshake size={18} aria-hidden="true" />需要帮助</a>
        </section>

        {offline && (
          <StatusBanner tone="offline" title="当前离线">
            可以先用电话联系家人。页面恢复连接前，不会把事项标记为已完成或已延后。
          </StatusBanner>
        )}
        {receipt && <StatusBanner tone="success" title="操作已确认">{receipt}</StatusBanner>}

        {loading ? (
          <LoadingState label="正在加载今日事项" />
        ) : error && tasks.length === 0 ? (
          <ErrorState description={error} onRetry={() => void load()} title="今日事项不可用" />
        ) : (
          <>
            {error && <ErrorState description={error} onRetry={() => void load(false)} title="今日事项未更新" />}
            {visibleTasks.length === 0 ? (
              <EmptyState
                title="今天没有待确认事项"
                description="如果需要新增提醒，可以在陪伴对话中说明任务、日期和时间。"
              />
            ) : (
              <section className={styles.taskList} aria-label="今日待确认事项">
                {visibleTasks.map((task) => {
                  const status = normalizeCareTaskStatus(task.status);
                  const canSnooze = ["pending", "due", "snoozed"].includes(status);
                  return (
                    <div className={styles.elderTaskCard} key={task.id}>
                      <CareTaskCard
                        task={task}
                        actionLabel="标记为完成"
                        actionBusy={busy?.id === task.id && busy.action === "complete"}
                        onAction={() => void handleComplete(task)}
                        secondaryAction={(
                          <div className={styles.taskSecondaryActions}>
                            {canSnooze && (
                              <Button
                                label="晚 30 分钟提醒"
                                variant="secondary"
                                isLoading={busy?.id === task.id && busy.action === "snooze"}
                                isDisabled={Boolean(busy)}
                                onClick={() => void handleSnooze(task)}
                                icon={<Icon icon={Clock3} size="sm" />}
                              />
                            )}
                            <a href="/elder/help">需要帮助</a>
                          </div>
                        )}
                      />
                    </div>
                  );
                })}
              </section>
            )}
          </>
        )}
      </div>
    </RoleShell>
  );
}
