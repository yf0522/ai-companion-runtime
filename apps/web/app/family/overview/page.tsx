"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, ChevronRight } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchCareTasks,
  fetchNotifications,
  type CareTaskItem,
  type NotificationItem,
  userFacingApiError,
} from "@/lib/api-client";
import FamilyAlertCard, { type FamilyNotificationItem } from "../_components/FamilyAlertCard";
import FamilyTaskCard from "../_components/FamilyTaskCard";
import {
  canonicalTaskStatus,
  isFamilyTaskActive,
  taskDueAt,
} from "../_lib/care-task";
import styles from "../family.module.css";

const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
type OverviewState = "loading" | "unknown" | "attention" | "clear";

const openingCopy: Record<OverviewState, { title: string; description: string }> = {
  loading: { title: "正在确认今天的照护状态", description: "正在同步告警与照护安排，请稍候。" },
  unknown: { title: "暂时无法确认是否有新的异常", description: "请稍后重试；如果情况紧急，请直接联系本人或照护运营。" },
  attention: { title: "今天需要你确认一件事", description: "先处理最需要关注的情况，再查看其他照护安排。" },
  clear: { title: "今天的照护安排都在正常进行", description: "目前没有未确认的异常，可以继续查看接下来的照护安排。" },
};

function alertTime(item: NotificationItem): number {
  const value = new Date(item.created_at).getTime();
  return Number.isFinite(value) ? value : 0;
}
function taskTime(task: CareTaskItem): number {
  const value = new Date(taskDueAt(task) || "").getTime();
  return Number.isFinite(value) ? value : Number.MAX_SAFE_INTEGER;
}

export default function FamilyOverviewPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<CareTaskItem[]>([]);
  const [alerts, setAlerts] = useState<FamilyNotificationItem[]>([]);
  const [notificationStatus, setNotificationStatus] = useState("persisted");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [activeTaskData, missedTaskData, notificationData] = await Promise.all([
        fetchCareTasks({ scope: "all", limit: 50 }),
        fetchCareTasks({ statuses: ["missed"], scope: "all", limit: 1 }),
        fetchNotifications(),
      ]);
      const mergedTasks = new Map<string, CareTaskItem>();
      [...missedTaskData, ...activeTaskData].forEach((task) => mergedTasks.set(task.id, task));
      setTasks(Array.from(mergedTasks.values()));
      setAlerts(notificationData.items as FamilyNotificationItem[]);
      setNotificationStatus(notificationData.status);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof ApiError && err.status === 403
        ? "当前家属账号还没有绑定可查看的长者。"
        : userFacingApiError(err, "家属概览加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  const openAlerts = useMemo(() => alerts
    .filter((item) => item.status !== "acknowledged" && !item.acknowledged_at)
    .sort((left, right) => {
      const severity = (severityOrder[left.severity] ?? 1.5) - (severityOrder[right.severity] ?? 1.5);
      return severity || alertTime(right) - alertTime(left);
    }), [alerts]);
  const activeTasks = useMemo(() => tasks.filter(isFamilyTaskActive).sort((a, b) => taskTime(a) - taskTime(b)), [tasks]);
  const missedTasks = useMemo(() => tasks.filter((task) => canonicalTaskStatus(task.status) === "missed").sort((a, b) => taskTime(b) - taskTime(a)), [tasks]);
  const primaryAlert = openAlerts[0];
  const primaryMissedTask = missedTasks[0];
  const overviewState: OverviewState = loading
    ? "loading"
    : error || notificationStatus === "unavailable"
      ? "unknown"
      : primaryAlert || primaryMissedTask
        ? "attention"
        : "clear";
  const opening = openingCopy[overviewState];

  return (
    <RoleShell role="family" title="家庭照护">
      <div className={`${styles.workspace} family-overview`}>
        <header className="family-opening">
          <p>家庭照护概览</p>
          <h2>{opening.title}</h2>
          <span>{opening.description}</span>
        </header>

        {notificationStatus === "unavailable" && (
          <div className={styles.notice} data-tone="warning" role="status">
            <strong>通知状态暂时不可用</strong>
            这不是“暂无告警”。请稍后重试，或联系照护运营确认投递情况。
          </div>
        )}

        {loading ? (
          <LoadingState label="正在同步家庭照护状态" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : (
          <>
            {primaryAlert ? (
              <FamilyAlertCard
                item={primaryAlert}
                featured
                primaryHref={`/family/alerts?focus=${encodeURIComponent(primaryAlert.id)}`}
                contactHref="/family/contacts"
              />
            ) : primaryMissedTask ? (
              <section className={styles.surface} aria-label="最需要关注的照护任务">
                <div className={styles.sectionHeading}>
                  <div>
                    <h3>有一项照护任务已经错过</h3>
                    <p>请先确认本人是否已处理，再决定是否重新安排。</p>
                  </div>
                </div>
                <div className={styles.stack} style={{ marginTop: 14 }}>
                  <FamilyTaskCard task={primaryMissedTask} compactHref="/family/tasks?view=attention" />
                </div>
              </section>
            ) : overviewState === "clear" ? (
              <section className="family-all-clear">
                <CheckCircle2 size={28} aria-hidden="true" />
                <div>
                  <h3>目前没有需要处理的异常</h3>
                  <p>如果出现风险、投递失败或错过的照护任务，会优先显示在这里。</p>
                </div>
              </section>
            ) : null}

            <section className="quiet-section">
              <div className="quiet-section-heading">
                <div>
                  <h3>接下来</h3>
                  <p>仍在进行或即将触发的照护任务</p>
                </div>
                <a href="/family/tasks">查看全部 <ChevronRight size={17} /></a>
              </div>
              {activeTasks.length > 0 ? (
                <div className={styles.stack}>
                  {activeTasks.slice(0, 2).map((task) => (
                    <FamilyTaskCard key={task.id} task={task} compactHref="/family/tasks" />
                  ))}
                </div>
              ) : (
                <p className="quiet-empty">暂无进行中的照护任务。</p>
              )}
            </section>

            <section className="care-status-summary" aria-label="当前照护状态">
              <h3>当前状态</h3>
              <div>
                <span><strong>{activeTasks.length}</strong> 项照护安排正在进行</span>
                {overviewState === "unknown" ? (
                  <>
                    <span><strong>待确认</strong> 告警状态暂时不可用</span>
                    <span><strong>{missedTasks.length || "待确认"}</strong> 错过任务记录</span>
                  </>
                ) : (
                  <>
                    <span><strong>{openAlerts.length}</strong> 件事情需要关注</span>
                    <span><strong>{missedTasks.length}</strong> 项任务已经错过</span>
                  </>
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
