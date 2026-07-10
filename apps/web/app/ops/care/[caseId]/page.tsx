"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  createOperatorCaseActivity,
  fetchOperatorCase,
  fetchOperatorCaseActivities,
  transitionOperatorCase,
  type OperatorCaseActivity,
  type OperatorCaseDetail,
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
  critical: "border-status-critical bg-status-critical-soft",
  high: "border-status-warning bg-status-warning-soft",
  medium: "border-status-info bg-status-info-soft",
  low: "border-status-success bg-status-success-soft",
};

function formatTime(value: string | null | undefined): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function evidencePreview(evidence: Record<string, unknown> | null | undefined): string {
  if (!evidence || Object.keys(evidence).length === 0) return "暂无结构化证据";
  return JSON.stringify(evidence, null, 2);
}

export default function OpsCareDetailPage({ params }: { params: { caseId: string } }) {
  const router = useRouter();
  const [item, setItem] = useState<OperatorCaseDetail | null>(null);
  const [activities, setActivities] = useState<OperatorCaseActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [caseData, activityData] = await Promise.all([
        fetchOperatorCase(params.caseId),
        fetchOperatorCaseActivities(params.caseId),
      ]);
      setItem(caseData);
      setActivities(activityData.items || []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "案件详情加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [params.caseId, router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAddActivity(event: React.FormEvent) {
    event.preventDefault();
    if (!note.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await createOperatorCaseActivity(params.caseId, {
        activity_type: "operator_note",
        summary: note.trim(),
      });
      setNote("");
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "活动记录未保存，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleTransition(status: string) {
    setSubmitting(true);
    setError(null);
    try {
      if (!item) return;
      await transitionOperatorCase(params.caseId, {
        status,
        expected_state_version: item.state_version || 1,
      });
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "案件状态未更新，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <RoleShell role="operator" title="案件详情" subtitle={params.caseId}>
      <div className="grid gap-4">
        {error && <ErrorState description={error} onRetry={load} />}
        {loading ? (
          <LoadingState label="正在加载案件详情" />
        ) : !item ? (
          <EmptyState title="没有找到案件" description="请返回照护队列选择一个仍可访问的案件。" />
        ) : (
          <>
            <StatusBanner tone={item.severity === "critical" ? "critical" : "info"} title="当前处置指令">
              {item.next_action || "请根据活动记录选择处理动作。"}
            </StatusBanner>
            <section className={`border p-4 text-ink ${severityTone[item.severity] || "border-border bg-surface"}`}>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted">Case Command</p>
                  <h2 className="mt-1 text-xl font-semibold text-ink">{item.summary || "照护案件"}</h2>
                  <p className="mt-2 font-mono text-xs text-muted">{item.id}</p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs font-semibold">
                  <span className="border border-current px-2.5 py-1">{severityLabels[item.severity] || item.severity}</span>
                  <span className="border border-current px-2.5 py-1">{statusLabels[item.status] || item.status}</span>
                </div>
              </div>
              <dl className="mt-4 grid gap-0 border-t border-border text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div className="border-b border-border p-3 sm:border-r lg:border-b-0">
                  <dt className="text-xs text-muted">负责人</dt>
                  <dd className="mt-1 font-medium text-ink">{item.owner_id || "未分配"}</dd>
                </div>
                <div className="border-b border-border p-3 lg:border-b-0 lg:border-r">
                  <dt className="text-xs text-muted">长者 / 家庭</dt>
                  <dd className="mt-1 font-mono text-xs text-ink">{item.elder_user_id || item.user_id}</dd>
                  <dd className="mt-1 font-mono text-xs text-muted">{item.household_id || "household unknown"}</dd>
                </div>
                <div className="border-b border-border p-3 sm:border-b-0 sm:border-r">
                  <dt className="text-xs text-muted">创建</dt>
                  <dd className="mt-1 text-ink">{formatTime(item.created_at)}</dd>
                </div>
                <div className="p-3">
                  <dt className="text-xs text-muted">处理时限</dt>
                  <dd className="mt-1 text-ink">{formatTime(item.due_at)}</dd>
                </div>
              </dl>
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" disabled={submitting} onClick={() => handleTransition("assigned")} className="btn-secondary">
                  标记处理中
                </button>
                <button type="button" disabled={submitting} onClick={() => handleTransition("resolved")} className="btn-primary">
                  标记已解决
                </button>
              </div>
            </section>
            <section className="grid gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.35fr)]">
              <div className="grid gap-4">
                <section className="border border-border bg-surface p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted">Evidence Handles</p>
                  <dl className="mt-3 grid gap-3 text-sm">
                    <div>
                      <dt className="text-xs text-muted">安全决策</dt>
                      <dd className="font-mono text-xs text-ink">{item.safety_decision_id || "none"}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted">通知投递</dt>
                      <dd className="font-mono text-xs text-ink">{item.notification_outbox_id || "none"}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted">处置结果</dt>
                      <dd className="text-ink">{item.resolution || "未记录"}</dd>
                    </div>
                  </dl>
                  <pre className="mt-3 max-h-52 overflow-auto border border-border bg-canvas p-3 text-xs leading-5 text-muted">
                    {evidencePreview(item.evidence)}
                  </pre>
                </section>
                <form onSubmit={handleAddActivity} className="border border-border bg-surface p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted">Operator Note</p>
                  <label className="mt-3 grid gap-1 text-sm font-medium text-ink">
                    处理记录
                    <textarea value={note} onChange={(event) => setNote(event.target.value)} className="min-h-28 rounded-md border border-border bg-surface px-3 py-2 text-base" />
                  </label>
                  <button type="submit" disabled={submitting || !note.trim()} className="btn-primary mt-3">
                    {submitting ? "保存中" : "保存活动"}
                  </button>
                </form>
              </div>
              <section className="grid content-start gap-3">
                <div className="border-b border-border pb-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted">Evidence Timeline</p>
                  <h2 className="text-lg font-semibold text-ink">活动时间线</h2>
                </div>
                {activities.length === 0 ? (
                  <EmptyState title="暂无活动" description="系统事件、联系尝试和运营记录会显示在这里。" />
                ) : (
                  activities.map((activity) => (
                    <article key={activity.id} className="border-l-4 border-primary bg-surface p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <h3 className="text-base font-semibold text-ink">{activity.summary}</h3>
                          <p className="mt-1 text-sm text-muted">
                            {activity.actor_type} · {activity.activity_type}
                            {activity.actor_id ? ` · ${activity.actor_id}` : ""}
                          </p>
                        </div>
                        <span className="text-sm text-muted">{formatTime(activity.created_at)}</span>
                      </div>
                    </article>
                  ))
                )}
              </section>
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
