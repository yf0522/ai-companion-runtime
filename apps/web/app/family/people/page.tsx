"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchCareCircle,
  inviteCareCircleMember,
  revokeCareCircleBinding,
  type CareCircleMember,
  type CareCircleResponse,
  userFacingApiError,
} from "@/lib/api-client";

const permissionLabels: Record<string, string> = {
  view_reminders: "查看照护任务",
  manage_reminders: "管理照护任务",
  view_alerts: "查看告警",
  manage_contacts: "管理联系人",
  view_summary: "查看摘要",
};

function roleLabel(role: string): string {
  return (
    {
      elder: "长者",
      primary_caregiver: "主要照护人",
      caregiver: "照护人",
      operator: "运营",
    }[role] || role
  );
}

export default function FamilyPeoplePage() {
  const router = useRouter();
  const [data, setData] = useState<CareCircleResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inviteTarget, setInviteTarget] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchCareCircle());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(
        err instanceof ApiError && err.status === 403
          ? "当前账号没有管理照护圈的权限。"
          : userFacingApiError(err, "人员和权限加载失败，请稍后重试。"),
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleInvite(event: React.FormEvent) {
    event.preventDefault();
    if (!inviteTarget.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const target = inviteTarget.trim();
      if (!target.includes("@")) {
        setError("当前邀请流程只支持邮箱；手机号邀请会在短信身份验证接入后开放。");
        return;
      }
      await inviteCareCircleMember({
        role: "caregiver",
        permissions: ["view_reminders", "view_alerts", "view_summary"],
        email: target,
      });
      setInviteTarget("");
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "邀请未保存，请检查联系方式后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevoke(member: CareCircleMember) {
    const bindingId = member.binding_id || member.id;
    setRevokingId(bindingId);
    setError(null);
    try {
      await revokeCareCircleBinding(bindingId);
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "撤销失败，权限仍保持原状态。"));
    } finally {
      setRevokingId(null);
    }
  }

  return (
    <RoleShell
      role="family"
      title="人员与权限"
      subtitle="管理家庭照护圈、成员授权范围和升级顺序。服务端仍是权限边界。"
    >
      <div className="product-grid lg:grid-cols-[360px_minmax(0,1fr)]">
        <form onSubmit={handleInvite} className="product-panel">
          <p className="eyebrow">Care circle</p>
          <h2 className="section-heading">邀请照护人</h2>
          <label className="mt-4 grid gap-1 text-base font-medium text-ink">
            邮箱
            <input
              value={inviteTarget}
              onChange={(event) => setInviteTarget(event.target.value)}
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base"
              placeholder="family@example.com"
              autoComplete="email"
            />
          </label>
          <p className="mt-2 text-sm leading-6 text-muted">
            新成员默认只能查看照护任务、告警和授权摘要，不能修改联系人。
          </p>
          <button type="submit" disabled={submitting || !inviteTarget.trim()} className="btn-primary mt-4 w-full">
            {submitting ? "邀请中" : "发送邀请"}
          </button>
        </form>

        <section className="product-panel">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="eyebrow">Access boundary</p>
              <h2 className="section-heading">成员与授权范围</h2>
            </div>
            <div className="metric-strip" aria-label="照护圈统计">
              <div>
                <p className="eyebrow">Members</p>
                <p className="text-2xl font-semibold text-ink">{data?.members.length ?? 0}</p>
              </div>
              <div>
                <p className="eyebrow">Caregivers</p>
                <p className="text-2xl font-semibold text-ink">
                  {data?.members.filter((member) => member.role !== "elder").length ?? 0}
                </p>
              </div>
            </div>
          </div>
          <div className="mt-4 grid gap-3">
          <StatusBanner tone="info" title="隐私边界">
            家属权限只覆盖必要照护状态。私人对话、长期记忆和原始音频需要单独授权。
          </StatusBanner>
          {error && <ErrorState description={error} onRetry={load} />}
          {loading ? (
            <LoadingState label="正在加载人员与权限" />
          ) : !data || data.members.length === 0 ? (
            <EmptyState title="还没有照护圈成员" description="邀请主要照护人后，会在这里显示权限和升级顺序。" />
          ) : (
            data.members.map((member) => (
              <article key={member.id} className="evidence-row">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex flex-wrap gap-2">
                      <span className="rounded-full border border-status-info bg-status-info-soft px-3 py-1 text-sm text-ink">
                        {roleLabel(member.role)}
                      </span>
                      <span className="rounded-full border border-border bg-canvas px-3 py-1 text-sm text-ink">
                        {member.status || "状态待确认"}
                      </span>
                    </div>
                    <h3 className="mt-3 text-lg font-semibold text-ink">{member.name || "未命名成员"}</h3>
                    <p className="mt-1 text-sm text-muted">
                      升级顺序：{member.escalation_order ?? "未设置"}
                    </p>
                    <ul className="mt-3 flex flex-wrap gap-2" aria-label="授权范围">
                      {(member.permissions || []).map((permission) => (
                        <li key={permission} className="rounded-md border border-border bg-canvas px-3 py-2 text-sm text-muted">
                          {permissionLabels[permission] || permission}
                        </li>
                      ))}
                    </ul>
                  </div>
                  {member.role !== "elder" && (
                    <button
                      type="button"
                      disabled={revokingId === (member.binding_id || member.id)}
                      onClick={() => handleRevoke(member)}
                      className="btn-secondary border-status-critical"
                    >
                      {revokingId === (member.binding_id || member.id) ? "撤销中" : "撤销权限"}
                    </button>
                  )}
                </div>
              </article>
            ))
          )}
          </div>
        </section>
      </div>
    </RoleShell>
  );
}
