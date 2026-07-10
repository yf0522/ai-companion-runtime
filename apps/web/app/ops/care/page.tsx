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

const severityTone: Record<string, string> = {
  critical: "border-status-critical bg-status-critical-soft text-ink",
  high: "border-status-warning bg-status-warning-soft text-ink",
  medium: "border-status-info bg-status-info-soft text-ink",
  low: "border-status-success bg-status-success-soft text-ink",
};

function nextActionFor(item: OperatorCaseItem): string {
  if (item.resolution) return "复核处置结果";
  if (item.status === "open") return item.owner_id ? "负责人接单并记录首次触达" : "分配负责人";
  if (item.status === "assigned") return "跟进照护方并补充证据";
  if (item.status === "resolved") return "确认关闭条件";
  return "查看案件证据";
}

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
      <div className="grid gap-4">
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
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted">Operator Queue</p>
                <h2 className="text-xl font-semibold text-ink">安全案件工作台</h2>
              </div>
              <div className="grid grid-cols-3 gap-2 text-sm sm:min-w-72">
                <div className="border-l-4 border-status-critical bg-surface px-3 py-2">
                  <div className="font-semibold text-ink">{cases.filter((item) => item.severity === "critical").length}</div>
                  <div className="text-xs text-muted">紧急</div>
                </div>
                <div className="border-l-4 border-status-warning bg-surface px-3 py-2">
                  <div className="font-semibold text-ink">{cases.filter((item) => item.status === "open").length}</div>
                  <div className="text-xs text-muted">待接单</div>
                </div>
                <div className="border-l-4 border-primary bg-surface px-3 py-2">
                  <div className="font-semibold text-ink">{cases.length}</div>
                  <div className="text-xs text-muted">总案件</div>
                </div>
              </div>
            </div>
            {cases.map((item) => (
              <article key={item.id} className="border border-border bg-surface">
                <div className="grid gap-0 lg:grid-cols-[minmax(0,1.4fr)_minmax(220px,0.7fr)_minmax(220px,0.8fr)_auto]">
                  <div className="min-w-0 border-b border-border p-4 lg:border-b-0 lg:border-r">
                    <div className="flex flex-wrap gap-2 text-xs font-semibold">
                      <span className={`border px-2.5 py-1 ${severityTone[item.severity] || "border-status-unknown bg-status-unknown-soft text-ink"}`}>
                        {severityLabels[item.severity] || "风险待确认"}
                      </span>
                      <span className="border border-border bg-canvas px-2.5 py-1 text-ink">
                        {statusLabels[item.status] || item.status}
                      </span>
                    </div>
                    <h3 className="mt-3 text-base font-semibold text-ink">{item.summary || "照护案件"}</h3>
                    <p className="mt-2 font-mono text-xs text-muted">Case {item.id}</p>
                  </div>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-border p-4 text-sm lg:border-b-0 lg:border-r">
                    <div>
                      <dt className="text-xs text-muted">负责人</dt>
                      <dd className="mt-1 font-medium text-ink">{item.owner_id || "未分配"}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted">长者</dt>
                      <dd className="mt-1 font-mono text-xs text-ink">{item.user_id}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted">创建</dt>
                      <dd className="mt-1 text-ink">{formatTime(item.created_at)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted">时限</dt>
                      <dd className="mt-1 text-ink">{formatTime(item.due_at)}</dd>
                    </div>
                  </dl>
                  <div className="grid gap-2 border-b border-border p-4 text-sm lg:border-b-0 lg:border-r">
                    <div>
                      <div className="text-xs text-muted">下一步</div>
                      <div className="mt-1 font-medium text-ink">{nextActionFor(item)}</div>
                    </div>
                    <div className="grid gap-1 font-mono text-xs text-muted">
                      <span>decision {item.safety_decision_id ? item.safety_decision_id.slice(0, 8) : "none"}</span>
                      <span>outbox {item.notification_outbox_id ? item.notification_outbox_id.slice(0, 8) : "none"}</span>
                    </div>
                  </div>
                  <div className="flex items-center p-4">
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
