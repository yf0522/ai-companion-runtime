"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Clipboard, Clock3, ExternalLink, FileCheck2, History, UserRoundCheck } from "lucide-react";
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
import {
  allowedCaseTransitions,
  caseOwnerLabel,
  caseSlaState,
  operatorSeverityLabel,
  operatorStatusLabel,
  transitionLabel,
} from "../../_lib/operator";
import styles from "../../operator.module.css";

const activityLabels: Record<string, string> = {
  operator_note: "运营记录",
  state_transition: "案件状态变化",
  notification_acknowledged: "家属确认处理",
  trace_viewed: "运营查看追踪证据",
  case_created: "案件创建",
};

const actorLabels: Record<string, string> = {
  operator: "运营人员",
  caregiver: "家属",
  elder: "长者",
  system: "系统",
};

function formatTime(value: string | null | undefined): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间待确认" : date.toLocaleString("zh-CN");
}

function shortId(value: string | null | undefined): string {
  if (!value) return "未关联";
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
}

function activityTitle(activity: OperatorCaseActivity): string {
  if (activity.activity_type === "state_transition" && activity.to_status) {
    return `${operatorStatusLabel(activity.from_status)} → ${operatorStatusLabel(activity.to_status)}`;
  }
  return activityLabels[activity.activity_type] || activity.summary || "案件活动";
}

function activitySummary(activity: OperatorCaseActivity): string {
  if (activity.activity_type === "state_transition") {
    const resolution = typeof activity.metadata?.resolution === "string" ? activity.metadata.resolution : null;
    return resolution || "状态由服务端合法状态机更新。";
  }
  return activity.summary || "没有补充说明。";
}

function copyText(value: string | null | undefined) {
  if (!value || !navigator.clipboard) return;
  void navigator.clipboard.writeText(value);
}

export default function OpsCareDetailPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params.caseId;
  const router = useRouter();
  const [item, setItem] = useState<OperatorCaseDetail | null>(null);
  const [activities, setActivities] = useState<OperatorCaseActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [resolution, setResolution] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [caseData, activityData] = await Promise.all([
        fetchOperatorCase(caseId),
        fetchOperatorCaseActivities(caseId),
      ]);
      setItem(caseData);
      setActivities(activityData.items || []);
      setResolution(caseData.resolution || "");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "案件详情加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [caseId, router]);

  useEffect(() => { void load(); }, [load]);

  async function handleAddActivity(event: React.FormEvent) {
    event.preventDefault();
    if (!note.trim() || !item?.can_add_activity) return;
    setSubmitting(true);
    setError(null);
    try {
      await createOperatorCaseActivity(caseId, {
        activity_type: "operator_note",
        summary: note.trim(),
      });
      setNote("");
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "活动记录未保存，原案件状态没有改变。"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleTransition(status: string) {
    if (!item || !allowedCaseTransitions(item).includes(status)) return;
    if (["resolved", "closed"].includes(status) && !resolution.trim()) {
      setError("解决或关闭案件前必须记录处置结论。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await transitionOperatorCase(caseId, {
        status,
        expected_state_version: item.state_version || 1,
        resolution: ["resolved", "closed"].includes(status) ? resolution.trim() : null,
      });
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "案件状态未更新，请刷新后确认当前负责人和状态。"));
    } finally {
      setSubmitting(false);
    }
  }

  const transitions = useMemo(() => item ? allowedCaseTransitions(item) : [], [item]);
  const sla = item ? caseSlaState(item.due_at) : null;
  const decision = item?.evidence?.safety_decision;
  const delivery = item?.evidence?.notification_delivery;

  return (
    <RoleShell role="operator" title="案件详情" subtitle="处置、证据与审计时间线">
      <div className={styles.workspace}>
        <header className={styles.pageHeader}>
          <div>
            <h2>案件处置</h2>
            <p>服务端决定合法动作；运营记录、家属确认、投递与追踪查看进入同一条时间线。</p>
          </div>
          <a className={styles.contextLink} href="/ops/care">返回案件队列</a>
        </header>

        {loading ? (
          <LoadingState label="正在加载案件详情" />
        ) : error && !item ? (
          <ErrorState description={error} onRetry={load} />
        ) : !item ? (
          <EmptyState title="没有找到案件" description="请返回照护队列选择一个仍可访问的案件。" />
        ) : (
          <>
            {error && <ErrorState title="操作没有完成" description={error} onRetry={load} />}
            <div className={styles.detailGrid}>
              <div className={styles.detailMain}>
                <section className={styles.commandPanel} data-severity={item.severity}>
                  <div className={styles.commandHeader}>
                    <div>
                      <span className={styles.contextLabel}>当前案件</span>
                      <h2>{item.summary || "照护案件"}</h2>
                    </div>
                    <div className={styles.badgeRow}>
                      <span className={styles.badge} data-tone={item.severity === "critical" ? "critical" : item.severity === "high" ? "warning" : "neutral"}>{operatorSeverityLabel(item.severity)}</span>
                      <span className={styles.badge}>{operatorStatusLabel(item.status)}</span>
                    </div>
                  </div>

                  <dl className={styles.facts}>
                    <div><dt>负责人</dt><dd><UserRoundCheck size={14} aria-hidden="true" /> {caseOwnerLabel(item)}</dd></div>
                    <div><dt>处理时限</dt><dd><Clock3 size={14} aria-hidden="true" /> {sla?.label || "未设置"}</dd></div>
                    <div><dt>家庭</dt><dd>{shortId(item.household_id)}</dd></div>
                    <div><dt>创建时间</dt><dd>{formatTime(item.created_at)}</dd></div>
                  </dl>

                  {transitions.some((status) => status === "resolved" || status === "closed") && (
                    <label className={styles.resolutionField}>
                      处置结论（解决或关闭时必填）
                      <textarea className={styles.textArea} value={resolution} onChange={(event) => setResolution(event.target.value)} placeholder="记录联系结果、风险是否解除和后续责任人" />
                    </label>
                  )}

                  <div className={styles.commandActions} aria-label="合法案件动作">
                    {transitions.length === 0 ? (
                      <span className={styles.cellHint}>{item.ownership_status === "owned_by_other" ? "案件由其他运营人员负责，当前账号只读。" : "当前状态没有可执行的后续转换。"}</span>
                    ) : transitions.map((status) => (
                      <button
                        key={status}
                        type="button"
                        disabled={submitting}
                        className={status === "assigned" ? styles.primaryButton : status === "closed" ? styles.dangerButton : styles.secondaryButton}
                        onClick={() => void handleTransition(status)}
                      >
                        {transitionLabel(item.status, status)}
                      </button>
                    ))}
                  </div>
                </section>

                <section className={styles.evidencePanel}>
                  <div className={styles.sectionHeading}>
                    <div><h2>授权证据</h2><p>证据句柄来自案件关系，不开放无关 Trace。</p></div>
                    <FileCheck2 size={20} aria-hidden="true" />
                  </div>
                  <div className={styles.evidenceGrid}>
                    <article className={styles.evidenceCard}>
                      <h3>安全决策</h3>
                      <dl>
                        <div><dt>风险类别</dt><dd>{decision?.risk_category || "未记录"}</dd></div>
                        <div><dt>策略版本</dt><dd>{decision?.policy_version || "未记录"}</dd></div>
                        <div><dt>建议动作</dt><dd>{decision?.action || "未记录"}</dd></div>
                        <div><dt>置信度</dt><dd>{decision?.confidence == null ? "未记录" : `${Math.round(decision.confidence * 100)}%`}</dd></div>
                      </dl>
                      {item.trace_id && <a className={`${styles.contextLink} ${styles.spacedContextLink}`} href={`/ops/traces/${item.trace_id}`}>查看案件追踪 <ExternalLink size={14} /></a>}
                    </article>
                    <article className={styles.evidenceCard}>
                      <h3>通知投递</h3>
                      <dl>
                        <div><dt>状态</dt><dd>{delivery?.state || "未记录"}</dd></div>
                        <div><dt>通道</dt><dd>{delivery?.provider || "未配置"} · {delivery?.channel || "未记录"}</dd></div>
                        <div><dt>尝试次数</dt><dd>{delivery?.attempt_count == null ? "未记录" : delivery.attempt_count}</dd></div>
                        <div><dt>最近错误</dt><dd>{delivery?.last_error || "无已记录错误"}</dd></div>
                      </dl>
                    </article>
                  </div>
                  <details className={styles.rawDetails}>
                    <summary>复制审计标识</summary>
                    <div className={styles.commandActions}>
                      {[
                        ["案件", item.id],
                        ["安全决策", item.safety_decision_id],
                        ["通知", item.notification_outbox_id],
                        ["追踪", item.trace_id],
                      ].map(([label, value]) => value && (
                        <button key={label} type="button" className={styles.compactButton} onClick={() => copyText(value)}><Clipboard size={14} />复制{label} ID</button>
                      ))}
                    </div>
                  </details>
                </section>

                <section className={styles.timelinePanel}>
                  <div className={styles.sectionHeading}>
                    <div><h2>案件时间线</h2><p>系统、家属和运营动作按实际发生顺序展示。</p></div>
                    <History size={20} aria-hidden="true" />
                  </div>
                  {activities.length === 0 ? (
                    <EmptyState title="暂无活动" description="状态变化、家属确认、联系尝试和查看证据会显示在这里。" />
                  ) : (
                    <div className={styles.timeline}>
                      {activities.map((activity) => (
                        <article key={activity.id} className={styles.timelineItem}>
                          <span className={styles.timelineDot} aria-hidden="true" />
                          <div className={styles.timelineBody}>
                            <h3>{activityTitle(activity)}</h3>
                            <p>{actorLabels[activity.actor_type] || activity.actor_type} · {activitySummary(activity)}</p>
                          </div>
                          <time className={styles.timelineTime}>{formatTime(activity.created_at)}</time>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
              </div>

              <aside className={styles.detailAside}>
                <StatusBanner tone={item.status === "unstaffed" ? "warning" : "info"} title="下一步">
                  {item.status === "unstaffed" ? "先接单，之后才能写入联系记录或处置活动。" : item.next_action || "根据证据和时间线完成下一步处置。"}
                </StatusBanner>

                {item.household_id && (
                  <section className={styles.householdPanel}>
                    <div className={styles.sectionHeading}><div><h2>关联家庭</h2><p>查看联系人、设备、任务和升级规则是否就绪。</p></div></div>
                    <a className={styles.contextLink} href={`/ops/households/readiness?household_id=${encodeURIComponent(item.household_id)}`}>打开家庭就绪 <ExternalLink size={14} /></a>
                  </section>
                )}

                <form onSubmit={handleAddActivity} className={styles.notePanel}>
                  <div className={styles.sectionHeading}><div><h2>运营记录</h2><p>{item.can_add_activity ? "记录联系、核实和交接结果。" : "接单后才能写入运营记录。"}</p></div></div>
                  <label className={styles.resolutionField}>
                    处理记录
                    <textarea className={styles.textArea} value={note} onChange={(event) => setNote(event.target.value)} disabled={!item.can_add_activity} placeholder="例如：已联系女儿，确认未发生转账" />
                  </label>
                  <button type="submit" disabled={submitting || !item.can_add_activity || !note.trim()} className={`${styles.primaryButton} ${styles.spacedPrimaryButton}`}>
                    {submitting ? "保存中" : "保存活动"}
                  </button>
                </form>
              </aside>
            </div>
          </>
        )}
      </div>
    </RoleShell>
  );
}
