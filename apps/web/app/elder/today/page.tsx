"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import CareTaskCard from "@/components/CareTaskCard";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  completeCareTask,
  fetchCareTasks,
  mutationInputForTask,
  type CareTaskItem,
  userFacingApiError,
} from "@/lib/api-client";

export default function ElderTodayPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<CareTaskItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [ackingId, setAckingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setOffline(!navigator.onLine);
    try {
      setTasks(await fetchCareTasks());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "今日事项加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
    const updateOnline = () => setOffline(!navigator.onLine);
    window.addEventListener("online", updateOnline);
    window.addEventListener("offline", updateOnline);
    return () => {
      window.removeEventListener("online", updateOnline);
      window.removeEventListener("offline", updateOnline);
    };
  }, [load]);

  async function handleAcknowledge(task: CareTaskItem) {
    setAckingId(task.id);
    setError(null);
    try {
      await completeCareTask(task.id, mutationInputForTask(task, "care-task-complete"));
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "确认失败，尚未记录为完成。"));
    } finally {
      setAckingId(null);
    }
  }

  const activeTasks = tasks.filter((task) => !["completed", "cancelled", "archived", "expired"].includes(task.status || ""));

  return (
    <RoleShell
      role="elder"
      title="今日事项"
      subtitle="只显示需要确认的照护事项；确认成功后才会记录为已处理。"
    >
      <div className="grid gap-4">
        {offline && (
          <StatusBanner tone="offline" title="当前离线">
            可以先用电话联系家人。页面恢复连接前，不会把事项标记为已确认。
          </StatusBanner>
        )}
        {error && (
          <ErrorState
            description={error}
            onRetry={load}
            title="今日事项不可用"
          />
        )}
        {loading ? (
          <LoadingState label="正在加载今日事项" />
        ) : activeTasks.length === 0 && !error ? (
          <EmptyState
            title="今天没有待确认事项"
            description="如果需要新增提醒，可以在陪伴对话中说明任务、日期和时间。"
          />
        ) : (
          activeTasks.map((task) => (
            <CareTaskCard
              key={task.id}
              task={task}
              actionLabel="确认已处理"
              actionBusy={ackingId === task.id}
              onAction={() => handleAcknowledge(task)}
            />
          ))
        )}
      </div>
    </RoleShell>
  );
}
