"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, CheckCircle2, Clock3, UserRound, Wrench } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchHouseholdReadiness,
  type HouseholdReadinessCheck,
  type HouseholdReadinessResponse,
  userFacingApiError,
} from "@/lib/api-client";
import FamilyPageHeader from "../_components/FamilyPageHeader";
import styles from "../family.module.css";

type FamilyReadinessCheck = HouseholdReadinessCheck & {
  family_label?: string | null;
  family_detail?: string | null;
  owner?: string | null;
  owner_name?: string | null;
  action_label?: string | null;
  action_href?: string | null;
  action?: string | null;
  evidence_at?: string | null;
};

const safeCheckCopy: Record<string, { label: string; detail: string; owner: string; action?: string; href?: string }> = {
  platform: { label: "照护服务可用", detail: "确认提醒、通知与记录服务可以正常工作。", owner: "照护运营" },
  active_consent_binding: { label: "家庭授权有效", detail: "长者本人已同意至少一位家属查看必要照护结果。", owner: "长者本人", action: "查看人员与权限", href: "/family/people" },
  verified_contact: { label: "至少一个联系方式已验证", detail: "风险发生时，系统有经过验证的号码或地址可以尝试联系。", owner: "联系方式管理员", action: "检查联系方式", href: "/family/contacts" },
  production_provider_delivery_test: { label: "通知投递已经实测", detail: "至少有一次通知获得服务商接受、送达或已读回执。", owner: "照护运营", action: "查看联系设置", href: "/family/contacts" },
  enrolled_active_device: { label: "长者设备已经连接", detail: "长者使用的设备已完成登记，且当前凭据仍然有效。", owner: "长者本人或照护运营" },
  active_care_task: { label: "已有进行中的照护任务", detail: "家庭已经建立至少一项当前有效的照护安排。", owner: "有任务管理权限的家属", action: "查看照护任务", href: "/family/tasks" },
  active_escalation_policy: { label: "风险升级顺序已配置", detail: "风险发生后由谁先接手、何时继续升级已经单独记录。", owner: "长者本人", action: "检查联系与升级设置", href: "/family/contacts" },
};
const statusLabels: Record<string, string> = { ready: "已就绪", missing: "尚未完成", warning: "需要确认", blocked: "当前受阻" };

function safeCopy(check: FamilyReadinessCheck) {
  const fallback = safeCheckCopy[check.key] || {
    label: "其他照护检查",
    detail: "服务返回了一项尚未转换为家庭说明的检查，请由照护运营确认。",
    owner: "照护运营",
  };
  return {
    label: check.family_label || fallback.label,
    detail: check.family_detail || fallback.detail,
    owner: check.owner_name || check.owner || fallback.owner,
    action: check.action_label || check.action || fallback.action,
    href: check.action_href || fallback.href,
  };
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "证据时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "证据时间待确认" : date.toLocaleString("zh-CN");
}

export default function FamilyReadinessPage() {
  const router = useRouter();
  const [data, setData] = useState<HouseholdReadinessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setData(await fetchHouseholdReadiness());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof ApiError && err.status === 403
        ? "当前账号没有查看这个家庭就绪状态的权限。"
        : userFacingApiError(err, "家庭就绪状态加载失败，请稍后重试。"));
    } finally { setLoading(false); }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  const checks = (data?.checks || []) as FamilyReadinessCheck[];
  const blockers = useMemo(() => checks.filter((check) => check.required && check.status !== "ready"), [checks]);
  const optionalWarnings = useMemo(() => checks.filter((check) => !check.required && check.status !== "ready"), [checks]);
  const readyCount = checks.filter((check) => check.status === "ready").length;

  return (
    <RoleShell role="family" title="家庭就绪检查">
      <div className={styles.workspace}>
        <FamilyPageHeader
          context="照护路径"
          title={blockers.length > 0 ? `还有 ${blockers.length} 项会影响照护闭环` : "当前照护路径已经可以使用"}
          description="把授权、联系方式、任务、设备和真实投递证据放在一起检查；每个缺口都说明由谁处理。"
        />

        {loading ? (
          <LoadingState label="正在检查家庭照护准备情况" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : checks.length === 0 ? (
          <EmptyState title="暂无就绪数据" description="服务没有返回检查项目，因此不能判断家庭照护路径是否可用。" />
        ) : (
          <>
            <section className={styles.summaryGrid} aria-label="家庭就绪摘要">
              <div><dt>已完成</dt><dd>{readyCount} / {checks.length}</dd><small>来自当前检查记录</small></div>
              <div><dt>必要缺口</dt><dd>{blockers.length}</dd><small>会影响照护闭环</small></div>
              <div><dt>可选提醒</dt><dd>{optionalWarnings.length}</dd><small>不会被写成已就绪</small></div>
              <div><dt>证据更新时间</dt><dd style={{ fontSize: 15 }}>{formatTime(data?.updated_at)}</dd><small>不是持续在线保证</small></div>
            </section>

            <section className={styles.surface} aria-label="家庭就绪检查项">
              <div className={styles.sectionHeading}><div><h3>逐项确认</h3><p>先处理必要缺口；已完成项仍保留证据时间。</p></div></div>
              <div className={styles.checkList} style={{ marginTop: 18 }}>
                {[...checks].sort((a, b) => Number(a.status === "ready") - Number(b.status === "ready")).map((check) => {
                  const copy = safeCopy(check);
                  const ready = check.status === "ready";
                  return (
                    <article key={check.key} className={styles.checkCard}>
                      <div className={styles.relationLine}>
                        {ready ? <CheckCircle2 size={20} color="var(--care-success)" /> : <Wrench size={20} color="var(--care-warning)" />}
                        <h3>{copy.label}</h3>
                        <span className={styles.statePill} data-tone={ready ? "success" : check.status === "blocked" ? "critical" : "warning"}>{statusLabels[check.status] || "状态待确认"}</span>
                      </div>
                      <p style={{ margin: 0, color: "var(--care-muted)", lineHeight: 1.65 }}>{copy.detail}</p>
                      {!ready && copy.href && copy.action && <div className={styles.cardActions}><a className="btn-primary" href={copy.href}>{copy.action} <ArrowRight size={16} /></a></div>}
                      {!ready && !copy.href && <p className={styles.notice} data-tone="warning" style={{ margin: 0 }}><strong>由{copy.owner}处理</strong>当前没有安全的自助动作，请联系照护运营确认。</p>}
                      <dl className={styles.factGrid}>
                        <div><dt><UserRound size={16} />下一步负责人</dt><dd>{ready ? "当前无需处理" : copy.owner}</dd></div>
                        <div><dt><Clock3 size={16} />证据时间</dt><dd>{formatTime(check.evidence_at || check.updated_at || data?.updated_at)}</dd></div>
                      </dl>
                    </article>
                  );
                })}
              </div>
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
