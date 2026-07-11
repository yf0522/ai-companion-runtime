"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, ChevronRight, LockKeyhole } from "lucide-react";
import AlertCaseCard from "@/components/AlertCaseCard";
import CareTaskCard from "@/components/CareTaskCard";
import RoleShell from "@/components/RoleShell";
import { ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import { ApiError, fetchNotifications, fetchCareTasks, type NotificationItem, type CareTaskItem, userFacingApiError } from "@/lib/api-client";
import { isCareTaskActive } from "@/lib/care-task-state";

const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
type OverviewState = "loading" | "unknown" | "attention" | "clear";

const overviewCopy: Record<OverviewState, { title: string; description: string }> = {
  loading: {
    title: "正在确认今天的照护状态",
    description: "正在同步告警与照护安排，请稍候。",
  },
  unknown: {
    title: "暂时无法确认是否有新的异常",
    description: "请稍后重试；如果情况紧急，请直接联系本人或照护运营。",
  },
  attention: {
    title: "今天需要你确认一件事",
    description: "先处理需要关注的情况，其他照护安排仍可继续查看。",
  },
  clear: {
    title: "今天的照护安排都在正常进行",
    description: "目前没有未确认的异常，可以继续查看接下来的照护安排。",
  },
};

export default function FamilyOverviewPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<CareTaskItem[]>([]);
  const [alerts, setAlerts] = useState<NotificationItem[]>([]);
  const [notificationStatus, setNotificationStatus] = useState("persisted");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taskData, notificationData] = await Promise.all([fetchCareTasks(), fetchNotifications()]);
      setTasks(taskData);
      setAlerts(notificationData.items);
      setNotificationStatus(notificationData.status);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof ApiError && err.status === 403 ? "当前家属账号还没有绑定可查看的长者。" : userFacingApiError(err, "家属概览加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  const openAlerts = alerts
    .filter((item) => item.status !== "acknowledged")
    .sort((left, right) => (severityOrder[left.severity] ?? 1.5) - (severityOrder[right.severity] ?? 1.5));
  const activeTasks = tasks.filter(isCareTaskActive);
  const visibleActiveTasks = activeTasks.slice(0, 2);
  const primaryAlert = openAlerts[0];
  const overviewState: OverviewState = loading
    ? "loading"
    : error
      ? "unknown"
      : primaryAlert
        ? "attention"
        : notificationStatus === "unavailable"
          ? "unknown"
          : "clear";
  const opening = overviewCopy[overviewState];

  return (
    <RoleShell role="family" title="家庭照护">
      <div className="family-overview">
        <header className="family-opening">
          <p>家庭照护概览</p>
          <h2>{opening.title}</h2>
          <span>{opening.description}</span>
        </header>

        {notificationStatus === "unavailable" && (
          <StatusBanner tone="warning" title="通知状态暂时不可用">
            这不是暂无告警。请稍后重试，或联系照护运营确认投递情况。
          </StatusBanner>
        )}

        {loading ? (
          <LoadingState label="正在同步家庭照护状态" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : (
          <>
            {overviewState === "attention" && primaryAlert ? (
              <AlertCaseCard
                item={primaryAlert}
                featured
                primaryHref="/family/alerts"
                secondaryHref="/family/contacts"
              />
            ) : overviewState === "clear" ? (
              <section className="family-all-clear">
                <CheckCircle2 size={28} aria-hidden="true" />
                <div>
                  <h3>目前没有需要处理的异常</h3>
                  <p>如果出现风险、投递失败或待确认事项，会优先显示在这里。</p>
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
              {visibleActiveTasks.length > 0 ? (
                <div className="quiet-task-list">
                  {visibleActiveTasks.map((task) => <CareTaskCard key={task.id} task={task} compact compactHref="/family/tasks" />)}
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
                    <span><strong>待确认</strong> 历史处理状态暂时不可用</span>
                  </>
                ) : (
                  <>
                    <span><strong>{openAlerts.length}</strong> 件事情需要关注</span>
                    <span><strong>{alerts.filter((item) => item.status === "acknowledged").length}</strong> 件异常已确认处理</span>
                  </>
                )}
              </div>
            </section>

            <p className="family-privacy"><LockKeyhole size={15} />只显示已授权的照护结果，不展示私人对话。</p>
          </>
        )}
      </div>
    </RoleShell>
  );
}
