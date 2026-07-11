"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut, ShieldCheck, UserRoundCheck } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchCareCircle,
  revokeCareCircleBinding,
  type CareCircleInvite,
  type CareCircleMember,
  type CareCircleResponse,
  userFacingApiError,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/authStore";
import FamilyPageHeader from "../_components/FamilyPageHeader";
import styles from "../family.module.css";

type FamilyMember = CareCircleMember & {
  user_id?: string | null;
  consent_status?: string | null;
  relationship?: string | null;
  updated_at?: string | null;
};
type FamilyCircle = Omit<CareCircleResponse, "members"> & { members: FamilyMember[] };

const permissionLabels: Record<string, string> = {
  view_reminders: "查看照护任务",
  manage_reminders: "管理照护任务",
  view_alerts: "查看告警",
  view_notifications: "查看通知结果",
  manage_contacts: "管理联系方式",
  view_summary: "查看照护摘要",
};
const roleLabels: Record<string, string> = {
  elder: "长者本人",
  primary_caregiver: "主要照护人",
  caregiver: "照护人",
  family: "家属",
  operator: "照护运营",
};
const statusLabels: Record<string, string> = {
  active: "授权有效",
  invited: "等待加入",
  paused: "已暂停",
  revoked: "已撤销",
  accepted: "已接受",
  pending: "待确认",
  expired: "已过期",
  denied: "已拒绝",
  owner: "本人所有",
};

function inviteTarget(invite: CareCircleInvite): string {
  return invite.email || invite.phone || "联系方式未记录";
}

export default function FamilyPeoplePage() {
  const router = useRouter();
  const currentUserId = useAuthStore((state) => state.userId);
  const [data, setData] = useState<FamilyCircle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchCareCircle() as FamilyCircle);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof ApiError && err.status === 403
        ? "当前账号没有查看这个照护圈的权限。"
        : userFacingApiError(err, "人员和权限加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  const currentMember = useMemo(() => data?.members.find((member) => member.user_id === currentUserId) || null, [currentUserId, data]);
  const activeMembers = data?.members.filter((member) => member.status !== "revoked") || [];
  const pendingInvites = (data?.invites || []).filter((invite) => ["pending", "invited"].includes(invite.status));

  async function handleLeave(member: FamilyMember) {
    const bindingId = member.binding_id;
    if (!bindingId || member.user_id !== currentUserId) return;
    if (!window.confirm("确定退出这个照护圈吗？退出后将无法继续查看照护任务、告警和摘要。")) return;
    setRevokingId(bindingId);
    setError(null);
    try {
      await revokeCareCircleBinding(bindingId);
      useAuthStore.getState().clearAuth();
      router.replace("/login");
    } catch (err) {
      setError(userFacingApiError(err, "退出失败，当前授权仍然有效。"));
    } finally {
      setRevokingId(null);
    }
  }

  return (
    <RoleShell role="family" title="人员与权限">
      <div className={styles.workspace}>
        <FamilyPageHeader
          context="照护关系"
          title="谁能看到哪些照护结果"
          description="这里只显示家庭关系、同意状态和授权范围。私人对话与长期记忆不会作为家庭动态展示。"
        />

        <div className={styles.notice} role="note">
          <strong>邀请与权限由长者本人决定</strong>
          家属可以查看自己的授权，也可以退出照护圈；不能替长者邀请他人、改变其他成员权限或撤销他人的关系。
        </div>

        {loading ? (
          <LoadingState label="正在加载人员与权限" />
        ) : error && !data ? (
          <ErrorState description={error} onRetry={load} />
        ) : !data || activeMembers.length === 0 ? (
          <EmptyState title="还没有照护圈成员" description="长者本人完成邀请与同意后，成员及其授权范围会显示在这里。" />
        ) : (
          <div className={styles.split}>
            <section className={styles.surface} aria-label="照护圈成员">
              <div className={styles.sectionHeading}>
                <div><h3>成员与授权</h3><p>{activeMembers.length} 位成员已记录；操作只对当前账号开放。</p></div>
              </div>
              {error && <div className={styles.notice} data-tone="critical" role="alert" style={{ marginTop: 14 }}>{error}</div>}
              <div className={styles.peopleList} style={{ marginTop: 18 }}>
                {activeMembers.map((member) => {
                  const isCurrent = member.user_id === currentUserId;
                  const canLeave = isCurrent && member.role !== "elder" && Boolean(member.binding_id);
                  return (
                    <article key={member.id} className={styles.personCard}>
                      <div className={styles.relationLine}>
                        <h3>{member.name || "未命名成员"}</h3>
                        {isCurrent && <span className={styles.statePill} data-tone="info">当前账号</span>}
                        <span className={styles.statePill} data-tone={member.status === "active" ? "success" : "warning"}>{statusLabels[member.status] || "状态待确认"}</span>
                      </div>
                      <div className={styles.metaLine}>
                        <span><UserRoundCheck size={15} /> {member.relationship || roleLabels[member.role] || "关系未记录"}</span>
                        <span><ShieldCheck size={15} /> 同意状态：{statusLabels[member.consent_status || ""] || "尚未记录"}</span>
                        <span>升级顺序：{member.escalation_order ?? "未配置"}</span>
                      </div>
                      <div>
                        <p className={styles.muted} style={{ margin: "0 0 8px", fontSize: 13 }}>授权范围</p>
                        {member.permissions?.length ? (
                          <ul className={styles.permissionList}>{member.permissions.map((permission) => <li key={permission}>{permissionLabels[permission] || "未识别的授权"}</li>)}</ul>
                        ) : <p className={styles.muted} style={{ margin: 0 }}>没有记录可用授权。</p>}
                      </div>
                      {canLeave && (
                        <div className={styles.cardActions}>
                          <button type="button" className="btn-secondary" disabled={revokingId === member.binding_id} onClick={() => handleLeave(member)}>
                            <LogOut size={16} /> {revokingId === member.binding_id ? "正在退出" : "退出照护圈"}
                          </button>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>

            <aside className={styles.stack}>
              <section className={styles.surfaceSoft} aria-label="当前账号权限摘要">
                <h3>你的访问范围</h3>
                <p className={styles.surfaceLead}>{currentMember
                  ? `当前账号有 ${currentMember.permissions.length} 项授权；长者本人可以随时调整或撤销。`
                  : "服务没有返回当前账号对应的成员记录，因此不提供权限修改动作。"}</p>
              </section>
              <section className={styles.surface} aria-label="待处理邀请">
                <div className={styles.sectionHeading}><div><h3>邀请记录</h3><p>邀请由长者本人发起。</p></div></div>
                {pendingInvites.length === 0 ? (
                  <p className={styles.empty} style={{ marginTop: 14 }}><strong>没有待处理邀请</strong>过期或已处理记录不会被当作当前成员。</p>
                ) : (
                  <div className={styles.peopleList} style={{ marginTop: 16 }}>
                    {pendingInvites.map((invite, index) => (
                      <article className={styles.personCard} key={`${inviteTarget(invite)}-${index}`}>
                        <div className={styles.relationLine}><h3>{inviteTarget(invite)}</h3><span className={styles.statePill} data-tone="warning">{statusLabels[invite.status] || "待确认"}</span></div>
                        <div className={styles.metaLine}><span>{roleLabels[invite.role] || "照护人"}</span><span>有效期至：{invite.expires_at ? new Date(invite.expires_at).toLocaleString("zh-CN") : "未记录"}</span></div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </aside>
          </div>
        )}
      </div>
    </RoleShell>
  );
}
