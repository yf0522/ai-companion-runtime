"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Clock3, Link2, Plus, ShieldAlert, TestTube2 } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  confirmContactVerification,
  createContact,
  deleteContact,
  fetchCareCircle,
  fetchContacts,
  fetchEmergencyContacts,
  fetchEscalationPolicies,
  fetchHouseholdReadiness,
  requestContactVerification,
  type CareCircleMember,
  type EmergencyContact,
  type EscalationPolicy,
  type HouseholdReadinessResponse,
  type VerifiedContact,
  userFacingApiError,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/authStore";
import FamilyPageHeader from "../_components/FamilyPageHeader";
import styles from "../family.module.css";

type ContactAvailability = { available?: boolean; label?: string; start?: string; end?: string; days?: string[] };
type FamilyContact = VerifiedContact & {
  availability?: ContactAvailability | null;
  verification_state?: string | null;
  status?: string | null;
  verified_at?: string | null;
  revoked_at?: string | null;
  last_test_at?: string | null;
  last_test_status?: string | null;
};
type CircleMember = CareCircleMember & { user_id?: string | null };

const channelLabels: Record<string, string> = { phone: "电话", sms: "短信", email: "邮件", wechat: "微信", webhook: "服务回调" };
const statusLabels: Record<string, string> = {
  verified: "已验证",
  challenge_pending: "验证码已发出",
  pending: "验证码已发出",
  failed: "验证失败",
  delivery_failed: "验证码未送达",
  unverified: "未验证",
  challenge_expired: "验证码已过期",
  challenge_locked: "验证已锁定",
  revoked: "已停用",
};
const policyActionLabels: Record<string, string> = {
  notify: "通知联系人",
  notify_contact: "通知联系人",
  call: "拨打电话",
  sms: "发送短信",
  email: "发送邮件",
  operator: "转交照护运营",
  escalate_operator: "转交照护运营",
};
const riskLevelLabels: Record<string, string> = { critical: "紧急", high: "高风险", medium: "中风险", low: "一般提醒" };

function formatTime(value: string | null | undefined): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间待确认" : date.toLocaleString("zh-CN");
}

function contactState(item: FamilyContact): string {
  return item.verification_state || item.verification_status || "unverified";
}

function availabilityLabel(item: FamilyContact): string {
  if (item.available === false || item.availability?.available === false) return "当前不可用";
  if (item.availability?.label) return item.availability.label;
  if (item.availability?.start || item.availability?.end) return `${item.availability.start || "开始时间未记录"}–${item.availability.end || "结束时间未记录"}`;
  return "可联系，时段未记录";
}

export default function FamilyContactsPage() {
  const router = useRouter();
  const currentUserId = useAuthStore((state) => state.userId);
  const [items, setItems] = useState<FamilyContact[]>([]);
  const [emergencyContacts, setEmergencyContacts] = useState<EmergencyContact[]>([]);
  const [policies, setPolicies] = useState<EscalationPolicy[]>([]);
  const [readiness, setReadiness] = useState<HouseholdReadinessResponse | null>(null);
  const [canManage, setCanManage] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [channel, setChannel] = useState("phone");
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [verificationCode, setVerificationCode] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [contactsResult, circleResult, readinessResult] = await Promise.allSettled([
      fetchContacts(),
      fetchCareCircle(),
      fetchHouseholdReadiness(),
    ]);
    try {
      if (contactsResult.status === "rejected") throw contactsResult.reason;
      setItems((contactsResult.value.items as FamilyContact[]).filter((item) => item.status !== "revoked" && !item.revoked_at && item.available !== false));
      if (circleResult.status === "fulfilled") {
        const member = (circleResult.value.members as CircleMember[]).find((candidate) => candidate.user_id === currentUserId);
        setCanManage(Boolean(member?.permissions.includes("manage_reminders")));
        const [emergencyResult, policiesResult] = await Promise.allSettled([
          fetchEmergencyContacts(),
          circleResult.value.household_id
            ? fetchEscalationPolicies(circleResult.value.household_id)
            : Promise.resolve({ items: [], total: 0 }),
        ]);
        setEmergencyContacts(emergencyResult.status === "fulfilled" ? emergencyResult.value.items.filter((item) => item.is_active !== false) : []);
        setPolicies(policiesResult.status === "fulfilled" ? policiesResult.value.items.filter((policy) => policy.status === "active") : []);
      } else {
        setCanManage(false);
        setEmergencyContacts([]);
        setPolicies([]);
      }
      setReadiness(readinessResult.status === "fulfilled" ? readinessResult.value : null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof ApiError && err.status === 403
        ? "当前账号没有查看这些联系方式的权限。"
        : userFacingApiError(err, "联系人加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [currentUserId, router]);

  useEffect(() => { void load(); }, [load]);

  const verifiedCount = items.filter((item) => contactState(item) === "verified").length;
  const escalationCheck = useMemo(() => readiness?.checks.find((check) => check.key === "active_escalation_policy") || null, [readiness]);
  const activePolicy = policies[0] || null;

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!canManage || !name.trim() || !value.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await createContact({
        name: name.trim(), channel, value: value.trim(), priority: items.length + 1, available: true,
      }) as FamilyContact;
      if (result.challenge_code_dev) setVerificationCode((prev) => ({ ...prev, [result.id]: result.challenge_code_dev || "" }));
      setName(""); setValue(""); setFormOpen(false);
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "联系方式未保存，原通知设置没有改变。"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(contact: FamilyContact) {
    if (!canManage) return;
    setBusyId(contact.id); setError(null);
    try {
      const result = await requestContactVerification(contact.id) as FamilyContact;
      if (result.challenge_code_dev) setVerificationCode((prev) => ({ ...prev, [contact.id]: result.challenge_code_dev || "" }));
      setItems((prev) => prev.map((item) => item.id === contact.id ? { ...item, ...result } : item));
    } catch (err) {
      setError(userFacingApiError(err, "验证请求未发出；当前联系方式仍未验证。"));
    } finally { setBusyId(null); }
  }

  async function handleConfirm(contact: FamilyContact) {
    const code = verificationCode[contact.id]?.trim();
    if (!canManage || !code) return;
    setBusyId(contact.id); setError(null);
    try {
      const result = await confirmContactVerification(contact.id, code) as FamilyContact;
      setVerificationCode((prev) => ({ ...prev, [contact.id]: "" }));
      setItems((prev) => prev.map((item) => item.id === contact.id ? { ...item, ...result } : item));
    } catch (err) {
      setError(userFacingApiError(err, "验证码未通过；请检查是否过期或已被锁定。"));
    } finally { setBusyId(null); }
  }

  async function handleDisable(contact: FamilyContact) {
    if (!canManage || !window.confirm(`确定停用“${contact.name}”的这个联系方式吗？已有历史会保留。`)) return;
    setBusyId(contact.id); setError(null);
    try {
      await deleteContact(contact.id);
      setItems((prev) => prev.filter((item) => item.id !== contact.id));
    } catch (err) {
      setError(userFacingApiError(err, "停用失败，这个联系方式仍然有效。"));
    } finally { setBusyId(null); }
  }

  return (
    <RoleShell role="family" title="已验证联系人">
      <div className={styles.workspace}>
        <FamilyPageHeader
          context="联系方法"
          title="确认哪些号码和地址真的可用"
          description="联系方式只证明可以尝试联系；是否进入风险升级顺序由单独的升级策略决定。"
          action={canManage ? <button type="button" className="btn-primary" onClick={() => setFormOpen((open) => !open)}><Plus size={17} /> {formOpen ? "收起新增" : "新增联系方式"}</button> : undefined}
        />

        {!loading && !canManage && !error && <div className={styles.notice}><strong>当前为只读访问</strong>你的授权允许查看联系状态，但不允许新增、验证或停用联系方式。</div>}
        {error && items.length > 0 && <div className={styles.notice} data-tone="critical" role="alert"><strong>这次操作没有完成</strong>{error}</div>}

        {formOpen && canManage && (
          <section className={styles.surface} aria-label="新增联系方式">
            <div className={styles.sectionHeading}><div><h3>新增联系方式</h3><p>保存后仍需完成验证码确认，未验证不会被写成可投递。</p></div></div>
            <form className={styles.form} onSubmit={handleCreate} style={{ marginTop: 18 }}>
              <div className={styles.formRow}>
                <label className={styles.field}>姓名或称呼<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
                <label className={styles.field}>渠道<select value={channel} onChange={(event) => setChannel(event.target.value)}><option value="phone">电话</option><option value="sms">短信</option><option value="email">邮件</option><option value="wechat">微信</option></select></label>
              </div>
              <label className={styles.field}>号码或地址<input value={value} onChange={(event) => setValue(event.target.value)} required /></label>
              <div className={styles.formActions}><button type="submit" className="btn-primary" disabled={submitting || !name.trim() || !value.trim()}>{submitting ? "保存中" : "保存并开始验证"}</button><button type="button" className="btn-secondary" onClick={() => setFormOpen(false)}>取消</button></div>
            </form>
          </section>
        )}

        {loading ? (
          <LoadingState label="正在加载联系人" />
        ) : error && items.length === 0 ? (
          <ErrorState description={error} onRetry={load} />
        ) : items.length === 0 ? (
          <EmptyState title="还没有联系人" description="添加并验证联系方式后，才能把它纳入单独配置的风险升级策略。" />
        ) : (
          <div className={styles.split}>
            <section className={styles.surface} aria-label="联系方式列表">
              <div className={styles.sectionHeading}><div><h3>联系端点</h3><p>{verifiedCount} / {items.length} 个已经完成验证。</p></div></div>
              <div className={styles.contactList} style={{ marginTop: 18 }}>
                {items.map((item) => {
                  const state = contactState(item);
                  const verified = state === "verified";
                  const codePending = state === "challenge_pending" || state === "pending";
                  return (
                    <article key={item.id} className={styles.contactCard}>
                      <div className={styles.relationLine}>
                        <h3>{item.name}</h3>
                        <span className={styles.statePill} data-tone={verified ? "success" : state.includes("failed") || state.includes("locked") ? "critical" : "warning"}>{statusLabels[state] || "状态待确认"}</span>
                        <span className={styles.statePill} data-tone="info">{channelLabels[item.channel] || "其他渠道"}</span>
                      </div>
                      <p style={{ margin: 0, fontSize: 16 }}>{item.value}</p>
                      <dl className={styles.factGrid}>
                        <div><dt><Clock3 size={16} />可联系时段</dt><dd>{availabilityLabel(item)}</dd></div>
                        <div><dt><CheckCircle2 size={16} />最近验证</dt><dd>{formatTime(item.last_verified_at || item.verified_at)}</dd></div>
                        <div><dt><TestTube2 size={16} />最近投递测试</dt><dd>{item.last_test_at ? `${formatTime(item.last_test_at)} · ${item.last_test_status || "结果待确认"}` : "未记录"}</dd></div>
                        <div><dt><Link2 size={16} />端点优先级</dt><dd>{item.priority ?? "未记录"}（不等于升级策略顺序）</dd></div>
                      </dl>
                      {canManage && !verified && (
                        <div className={styles.inlineForm}>
                          {codePending && <label className={styles.field}>验证码<input inputMode="numeric" value={verificationCode[item.id] || ""} onChange={(event) => setVerificationCode((prev) => ({ ...prev, [item.id]: event.target.value }))} placeholder="输入收到的验证码" /></label>}
                          <div className={styles.cardActions}>
                            {codePending && <button type="button" className="btn-primary" disabled={!verificationCode[item.id]?.trim() || busyId === item.id} onClick={() => handleConfirm(item)}>确认验证码</button>}
                            <button type="button" className="btn-secondary" disabled={busyId === item.id} onClick={() => handleVerify(item)}>{codePending ? "重新发送验证码" : "开始验证"}</button>
                          </div>
                        </div>
                      )}
                      {canManage && <div className={styles.cardActions}><button type="button" className="btn-secondary" disabled={busyId === item.id} onClick={() => handleDisable(item)}>停用这个端点</button></div>}
                    </article>
                  );
                })}
              </div>
            </section>

            <aside className={styles.stack}>
              <section className={styles.surfaceSoft} aria-label="升级策略状态">
                <div className={styles.relationLine}><ShieldAlert size={21} /><h3>风险升级策略</h3></div>
                {activePolicy ? (
                  <>
                    <p className={styles.surfaceLead}>“{activePolicy.name || "家庭风险升级策略"}”已启用，共 {activePolicy.steps.length} 步。端点只有被策略步骤引用后，才属于通知链路。</p>
                    <ol className={styles.stack} style={{ margin: "14px 0 0", paddingLeft: 20, color: "var(--care-muted)", lineHeight: 1.65 }}>
                      {activePolicy.steps.map((step) => <li key={`${activePolicy.id}-${step.step_order}`}>第 {step.step_order} 步：{policyActionLabels[step.action] || "执行已配置的联系动作"}{step.delay_seconds ? `，等待 ${Math.round(step.delay_seconds / 60)} 分钟后继续` : ""}</li>)}
                    </ol>
                    <p className={styles.metaLine} style={{ margin: "14px 0 0" }}>版本 {activePolicy.version} · 更新于 {formatTime(activePolicy.updated_at)}</p>
                  </>
                ) : escalationCheck ? (
                  <>
                    <p className={styles.surfaceLead}>{escalationCheck.status === "ready" ? "已检测到启用中的升级策略。具体联系人顺序仍以策略记录为准。" : "尚未检测到可用的升级策略；已验证端点不会因此自动收到风险通知。"}</p>
                    <span className={styles.statePill} data-tone={escalationCheck.status === "ready" ? "success" : "warning"}>{escalationCheck.status === "ready" ? "策略已启用" : "需要本人配置"}</span>
                  </>
                ) : <p className={styles.surfaceLead}>服务尚未返回升级策略证据，不能根据端点优先级推断通知顺序。</p>}
              </section>
              <section className={styles.surface} aria-label="升级联系人关系">
                <h3>进入策略的联系人</h3>
                {emergencyContacts.length === 0 ? <p className={styles.surfaceLead}>尚未返回已启用的升级联系人；已验证端点不会自动填入这里。</p> : (
                  <div className={styles.peopleList} style={{ marginTop: 14 }}>
                    {emergencyContacts.map((contact) => <article key={contact.id} className={styles.personCard}><div className={styles.relationLine}><strong>{contact.name}</strong><span className={styles.statePill} data-tone="success">顺序 {contact.priority ?? "未记录"}</span></div><div className={styles.metaLine}><span>{contact.relation || "关系未记录"}</span><span>接收等级：{contact.notify_on_levels?.map((level) => riskLevelLabels[level] || "未识别等级").join("、") || "未记录"}</span></div></article>)}
                  </div>
                )}
              </section>
              <section className={styles.surface} aria-label="联系链路说明">
                <h3>三件事分别确认</h3>
                <ol className={styles.stack} style={{ margin: "14px 0 0", paddingLeft: 20, color: "var(--care-muted)", lineHeight: 1.65 }}>
                  <li>端点完成验证</li><li>长者本人同意家庭授权</li><li>升级策略明确通知顺序</li>
                </ol>
              </section>
            </aside>
          </div>
        )}
      </div>
    </RoleShell>
  );
}
