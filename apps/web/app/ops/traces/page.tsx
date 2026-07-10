"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import { ApiError, fetchTraces, userFacingApiError } from "@/lib/api-client";

type TraceListItem = {
  trace_id?: string;
  id?: string;
  started_at?: string;
  created_at?: string;
  user_id?: string;
  status?: string;
};

function statusTone(status: string | undefined): string {
  if (status === "success" || status === "completed") return "border-status-success bg-status-success-soft text-ink";
  if (status === "failed" || status === "error") return "border-status-critical bg-status-critical-soft text-ink";
  if (status === "timeout") return "border-status-warning bg-status-warning-soft text-ink";
  return "border-status-unknown bg-status-unknown-soft text-ink";
}

function nextActionFor(status: string | undefined): string {
  if (status === "failed" || status === "error") return "打开追踪并定位失败步骤";
  if (status === "timeout") return "检查慢步骤和工具延迟";
  if (status === "success" || status === "completed") return "抽查模型、工具、投递证据";
  return "确认链路状态";
}

function traceIdOf(item: TraceListItem): string {
  return item.trace_id || item.id || "";
}

export default function OpsTracesPage() {
  const router = useRouter();
  const [items, setItems] = useState<TraceListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchTraces(20, 0);
      const rows = Array.isArray(data)
        ? data
        : Array.isArray((data as { items?: unknown[] }).items)
          ? (data as { items: TraceListItem[] }).items
          : [];
      setItems(rows);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "追踪列表加载失败，请稍后重试。"));
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
      title="追踪"
      subtitle="技术追踪只在运营角色下展示，用于重建模型、工具、策略和投递链路。"
    >
      <div className="grid gap-4">
        {error && <ErrorState description={error} onRetry={load} />}
        {loading ? (
          <LoadingState label="正在加载追踪列表" />
        ) : items.length === 0 && !error ? (
          <EmptyState title="暂无追踪记录" description="有可查看的运行记录后会显示在这里。" />
        ) : (
          <section className="grid gap-3">
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted">Trace Operations</p>
                <h2 className="text-xl font-semibold text-ink">运行证据队列</h2>
              </div>
              <div className="text-sm text-muted">{items.length} 条最近链路</div>
            </div>
            {items.map((item) => {
              const traceId = traceIdOf(item);
              return (
                <Link
                  key={traceId}
                  href={`/ops/traces/${traceId}`}
                  className="border border-border bg-surface text-ink hover:border-primary"
                >
                  <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_180px_minmax(220px,0.8fr)_auto]">
                    <div className="min-w-0 border-b border-border p-4 lg:border-b-0 lg:border-r">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted">Trace ID</p>
                      <div className="mt-1 break-all font-mono text-sm">{traceId || "unknown"}</div>
                    </div>
                    <div className="border-b border-border p-4 lg:border-b-0 lg:border-r">
                      <p className="text-xs text-muted">严重度 / 状态</p>
                      <span className={`mt-2 inline-flex border px-2.5 py-1 text-xs font-semibold ${statusTone(item.status)}`}>
                        {item.status || "unknown"}
                      </span>
                    </div>
                    <div className="border-b border-border p-4 text-sm lg:border-b-0 lg:border-r">
                      <p className="text-xs text-muted">负责人 / 下一步</p>
                      <p className="mt-1 font-medium text-ink">运营值班</p>
                      <p className="mt-1 text-muted">{nextActionFor(item.status)}</p>
                    </div>
                    <div className="grid gap-2 p-4 text-sm">
                      <span className="text-muted">时间：{item.started_at || item.created_at || "unknown"}</span>
                      <span className="font-mono text-xs text-muted">user {item.user_id || "unknown"}</span>
                    </div>
                  </div>
                </Link>
              );
            })}
          </section>
        )}
      </div>
    </RoleShell>
  );
}
