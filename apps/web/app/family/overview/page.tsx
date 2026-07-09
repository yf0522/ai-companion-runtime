"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AlertCaseCard from "@/components/AlertCaseCard";
import CareTaskCard from "@/components/CareTaskCard";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchNotifications,
  fetchReminders,
  type NotificationItem,
  type ReminderItem,
  userFacingApiError,
} from "@/lib/api-client";

export default function FamilyOverviewPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<ReminderItem[]>([]);
  const [alerts, setAlerts] = useState<NotificationItem[]>([]);
  const [notificationStatus, setNotificationStatus] = useState<string>("persisted");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taskData, notificationData] = await Promise.all([
        fetchReminders(),
        fetchNotifications(),
      ]);
      setTasks(taskData);
      setAlerts(notificationData.items);
      setNotificationStatus(notificationData.status);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setError("当前家属账号还没有绑定可查看的长者。");
      } else {
        setError(userFacingApiError(err, "家属概览加载失败，请稍后重试。"));
      }
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  const openAlerts = alerts.filter((item) => item.status !== "acknowledged");
  const activeTasks = tasks.filter((task) => task.is_active).slice(0, 3);

  return (
    <RoleShell
      role="family"
      title="家属概览"
      subtitle="先看需要关注的异常，再看即将发生的照护事项。默认不展示长者私人对话。"
    >
      <div className="grid gap-5">
        {notificationStatus === "unavailable" && (
          <StatusBanner tone="warning" title="通知状态暂时不可用">
            这不是“暂无告警”。请稍后重试，或联系照护运营确认投递情况。
          </StatusBanner>
        )}
        {loading ? (
          <LoadingState label="正在加载家属概览" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : (
          <>
            <section className="grid gap-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-xl font-semibold text-ink">需要关注</h2>
                <Link href="/family/alerts" className="btn-secondary">
                  查看全部告警
                </Link>
              </div>
              {openAlerts.length === 0 ? (
                <EmptyState title="暂无需要处理的告警" description="告警会显示投递状态和后续动作，不会把未确认投递写成已通知。" />
              ) : (
                openAlerts.slice(0, 2).map((item) => (
                  <AlertCaseCard key={item.id} item={item} />
                ))
              )}
            </section>
            <section className="grid gap-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-xl font-semibold text-ink">接下来的照护任务</h2>
                <Link href="/family/tasks" className="btn-secondary">
                  管理任务
                </Link>
              </div>
              {activeTasks.length === 0 ? (
                <EmptyState title="暂无进行中的照护任务" description="创建任务时请写明事项、时间和重复方式，系统会按现有提醒接口投递。" />
              ) : (
                activeTasks.map((task) => <CareTaskCard key={task.id} task={task} />)
              )}
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
