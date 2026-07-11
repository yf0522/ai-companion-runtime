"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchFamilySummary,
  type FamilySummaryResponse,
  userFacingApiError,
} from "@/lib/api-client";

const statusLabels: Record<string, string> = {
  completed: "已完成",
  acknowledged: "已确认",
  missed: "已错过",
  failed: "失败",
  expired: "已过期",
  cancelled: "已取消",
  snoozed: "已延后",
};

const taskTypeLabels: Record<string, string> = {
  medication: "服药",
  appointment: "复诊或预约",
  hydration: "饮水",
  exercise: "运动",
};

function formatOutcomeTime(value: string | null): string {
  if (!value) return "未记录时间";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间记录异常" : date.toLocaleString("zh-CN");
}

export default function FamilySummaryPage() {
  const router = useRouter();
  const [data, setData] = useState<FamilySummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchFamilySummary());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(
        err instanceof ApiError && err.status === 403
          ? "当前家属账号还没有获得照护摘要权限。"
          : userFacingApiError(err, "照护摘要加载失败，请稍后重试。"),
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  const summary = data?.summary;

  return (
    <RoleShell
      role="family"
      title="摘要"
    >
      <div className="product-grid">
        <StatusBanner tone="info" title="隐私边界">
          这里仅汇总任务完成、错过、取消和延后状态，不包含长者聊天原文或长期记忆内容。
        </StatusBanner>
        {loading ? (
          <LoadingState label="正在加载照护摘要" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : !summary || summary.total_outcomes === 0 ? (
          <EmptyState title="暂无照护结果" description="任务产生完成、错过或取消结果后会显示在这里。" />
        ) : (
          <>
            <section className="metric-strip" aria-label="照护结果统计">
              {Object.entries(summary.by_status).map(([status, count]) => (
                <div key={status}>
                  <p className="eyebrow">{statusLabels[status] || status}</p>
                  <p className="text-2xl font-semibold text-ink">{count}</p>
                </div>
              ))}
            </section>

            <section className="product-panel">
              <p className="eyebrow">最近照护</p>
              <h2 className="section-heading">最近照护结果</h2>
              <div className="mt-4 grid gap-3">
              {summary.items.map((item) => (
                <div key={item.task_id} className="evidence-row">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="font-medium text-ink">
                      {taskTypeLabels[item.task_type] || "照护任务"}
                    </span>
                    <span className="text-sm text-muted">{statusLabels[item.status] || item.status}</span>
                  </div>
                  <div className="mt-2 text-sm text-muted">
                    {formatOutcomeTime(item.completed_at || item.due_at)}
                  </div>
                </div>
              ))}
              </div>
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
