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
      <div className="grid gap-3">
        {error && <ErrorState description={error} onRetry={load} />}
        {loading ? (
          <LoadingState label="正在加载追踪列表" />
        ) : items.length === 0 && !error ? (
          <EmptyState title="暂无追踪记录" description="有可查看的运行记录后会显示在这里。" />
        ) : (
          items.map((item) => {
            const traceId = traceIdOf(item);
            return (
              <Link
                key={traceId}
                href={`/ops/traces/${traceId}`}
                className="rounded-md border border-border bg-surface p-4 text-ink hover:border-primary"
              >
                <div className="font-mono text-sm">{traceId}</div>
                <div className="mt-2 text-sm text-muted">
                  状态：{item.status || "unknown"} · 时间：
                  {item.started_at || item.created_at || "unknown"}
                </div>
              </Link>
            );
          })
        )}
      </div>
    </RoleShell>
  );
}
