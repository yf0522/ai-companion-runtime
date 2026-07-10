"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchOperatorCases,
  type OperatorCaseItem,
  userFacingApiError,
} from "@/lib/api-client";

const severityLabels: Record<string, string> = {
  critical: "紧急",
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

const statusLabels: Record<string, string> = {
  open: "待处理",
  assigned: "处理中",
  resolved: "已解决",
  closed: "已关闭",
};

function formatTime(value: string | null): string {
  if (!value) return "未设置";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间异常" : date.toLocaleString("zh-CN");
}

export default function OpsCarePage() {
  const router = useRouter();
  const [cases, setCases] = useState<OperatorCaseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCases((await fetchOperatorCases()).items);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(
        err instanceof ApiError && err.status === 403
          ? "当前账号不是照护运营角色。"
          : userFacingApiError(err, "照护队列加载失败，请稍后重试。"),
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <RoleShell
      role="operator"
      title="照护队列"
      subtitle="运营人员处理高风险事件、投递异常和需要人工跟进的照护案件。"
    >
      <div className="grid gap-5">
        <StatusBanner tone="info" title="操作边界">
          案件来自已持久化的安全决策和通知链路。运营页面展示处理证据，不展示长者私人聊天全文。
        </StatusBanner>
        {loading ? (
          <LoadingState label="正在加载运营案件" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : cases.length === 0 ? (
          <EmptyState title="暂无待处理案件" description="高风险事件或通知投递异常出现后会进入这里。" />
        ) : (
          <section className="grid gap-3">
            <h2 className="text-xl font-semibold text-ink">待处理案件</h2>
            {cases.map((item) => (
              <article key={item.id} className="rounded-md border border-border bg-surface p-4">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap gap-2 text-sm">
                      <span className="rounded-full border border-status-critical bg-status-critical-soft px-3 py-1 text-ink">
                        {severityLabels[item.severity] || "风险待确认"}
                      </span>
                      <span className="rounded-full border border-border bg-canvas px-3 py-1 text-ink">
                        {statusLabels[item.status] || item.status}
                      </span>
                    </div>
                    <h3 className="mt-3 text-lg font-semibold text-ink">{item.summary || "照护案件"}</h3>
                    <p className="mt-2 text-sm text-muted">创建时间：{formatTime(item.created_at)}</p>
                    <p className="mt-1 text-sm text-muted">处理时限：{formatTime(item.due_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {item.safety_decision_id && (
                      <span className="rounded-md border border-border bg-canvas px-3 py-2 font-mono text-xs text-muted">
                        决策 {item.safety_decision_id.slice(0, 8)}
                      </span>
                    )}
                    {item.notification_outbox_id && (
                      <span className="rounded-md border border-border bg-canvas px-3 py-2 font-mono text-xs text-muted">
                        投递 {item.notification_outbox_id.slice(0, 8)}
                      </span>
                    )}
                    <Link href={`/ops/care/${item.id}`} className="btn-secondary">
                      查看案件
                    </Link>
                  </div>
                </div>
              </article>
            ))}
          </section>
        )}
      </div>
    </RoleShell>
  );
}
