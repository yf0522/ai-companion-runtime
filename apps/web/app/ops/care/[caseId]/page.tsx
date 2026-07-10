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

function formatTime(value: string | null | undefined): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
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
      <div className="grid gap-5">
        {error && <ErrorState description={error} onRetry={load} />}
        {loading ? (
          <LoadingState label="正在加载案件详情" />
        ) : !item ? (
          <EmptyState title="没有找到案件" description="请返回照护队列选择一个仍可访问的案件。" />
        ) : (
          <>
            <StatusBanner tone={item.severity === "critical" ? "critical" : "info"} title={item.summary || "照护案件"}>
              当前状态：{item.status}。下一步：{item.next_action || "请根据活动记录选择处理动作。"}
            </StatusBanner>
            <section className="grid gap-3 rounded-md border border-border bg-surface p-4">
              <h2 className="text-xl font-semibold text-ink">案件证据</h2>
              <dl className="grid gap-3 text-sm text-muted sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <dt className="font-medium text-ink">长者</dt>
                  <dd>{item.elder_user_id || item.user_id}</dd>
                </div>
                <div>
                  <dt className="font-medium text-ink">负责人</dt>
                  <dd>{item.owner_id || "未分配"}</dd>
                </div>
                <div>
                  <dt className="font-medium text-ink">创建时间</dt>
                  <dd>{formatTime(item.created_at)}</dd>
                </div>
                <div>
                  <dt className="font-medium text-ink">处理时限</dt>
                  <dd>{formatTime(item.due_at)}</dd>
                </div>
              </dl>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={submitting} onClick={() => handleTransition("assigned")} className="btn-secondary">
                  标记处理中
                </button>
                <button type="button" disabled={submitting} onClick={() => handleTransition("resolved")} className="btn-primary">
                  标记已解决
                </button>
              </div>
            </section>
            <form onSubmit={handleAddActivity} className="rounded-md border border-border bg-surface p-4">
              <h2 className="text-xl font-semibold text-ink">新增活动</h2>
              <label className="mt-3 grid gap-1 text-base font-medium text-ink">
                处理记录
                <textarea value={note} onChange={(event) => setNote(event.target.value)} className="min-h-24 rounded-md border border-border bg-surface px-3 py-2 text-base" />
              </label>
              <button type="submit" disabled={submitting || !note.trim()} className="btn-primary mt-3">
                {submitting ? "保存中" : "保存活动"}
              </button>
            </form>
            <section className="grid gap-3">
              <h2 className="text-xl font-semibold text-ink">活动时间线</h2>
              {activities.length === 0 ? (
                <EmptyState title="暂无活动" description="系统事件、联系尝试和运营记录会显示在这里。" />
              ) : (
                activities.map((activity) => (
                  <article key={activity.id} className="rounded-md border border-border bg-surface p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-base font-semibold text-ink">{activity.summary}</h3>
                      <span className="text-sm text-muted">{formatTime(activity.created_at)}</span>
                    </div>
                    <p className="mt-1 text-sm text-muted">
                      {activity.actor_type} · {activity.activity_type}
                    </p>
                  </article>
                ))
              )}
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
