"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchHouseholdReadiness,
  type HouseholdReadinessResponse,
  userFacingApiError,
} from "@/lib/api-client";

const statusLabels: Record<string, string> = {
  ready: "已就绪",
  not_ready: "未就绪",
  blocked: "已阻塞",
  missing: "缺失",
  warning: "需确认",
};

function toneFor(status: string): string {
  if (status === "ready") return "border-status-success bg-status-success-soft";
  if (status === "blocked" || status === "missing") return "border-status-critical bg-status-critical-soft";
  return "border-status-warning bg-status-warning-soft";
}

export default function HouseholdReadinessView({
  role = "family",
  title = "家庭就绪检查",
  subtitle = "上线前确认同意、联系人、设备、通知渠道和首个照护任务。",
  householdId,
}: {
  role?: "family" | "operator";
  title?: string;
  subtitle?: string;
  householdId?: string;
}) {
  const router = useRouter();
  const [data, setData] = useState<HouseholdReadinessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (role === "operator" && !householdId) {
        setData(null);
        setError("运营查看家庭就绪状态时必须指定 household_id。");
        return;
      }
      setData(await fetchHouseholdReadiness(householdId));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "家庭就绪状态加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [householdId, role, router]);

  useEffect(() => {
    load();
  }, [load]);

  const readyChecks = data?.checks.filter((check) => check.status === "ready").length ?? 0;
  const requiredChecks = data?.checks.filter((check) => check.required).length ?? 0;

  return (
    <RoleShell role={role} title={title} subtitle={subtitle}>
      <div className="grid gap-4">
        {error && <ErrorState description={error} onRetry={load} />}
        {loading ? (
          <LoadingState label="正在加载家庭就绪检查" />
        ) : !data ? (
          <EmptyState title="暂无就绪数据" description="服务端返回就绪检查后会显示每个上线前置条件。" />
        ) : (
          <>
            <StatusBanner tone={data.status === "ready" ? "success" : "warning"} title={statusLabels[data.status] || data.status}>
              {data.next_action || "请确认所有必需项都处于已就绪状态。"}
            </StatusBanner>
            <section className="metric-strip" aria-label="家庭就绪统计">
              <div>
                <p className="eyebrow">整体状态</p>
                <p className="mt-1 text-base font-semibold text-ink">{statusLabels[data.status] || data.status}</p>
              </div>
              <div>
                <p className="eyebrow">已就绪</p>
                <p className="mt-1 text-2xl font-semibold text-ink">{readyChecks}</p>
              </div>
              <div>
                <p className="eyebrow">必需检查</p>
                <p className="mt-1 text-2xl font-semibold text-ink">{requiredChecks}</p>
              </div>
            </section>
            <section className="product-panel">
              <p className="eyebrow">上线检查</p>
              <h2 className="section-heading">上线前置条件</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {data.checks.map((check) => (
                  <article key={check.key} className={`rounded-md border p-4 text-ink ${toneFor(check.status)}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-lg font-semibold">{check.label}</h3>
                      <span className="status-pill border-border bg-surface text-ink">
                        {statusLabels[check.status] || check.status}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-6">{check.detail || (check.required ? "试点必需项" : "可选项")}</p>
                  </article>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
