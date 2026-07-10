"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  createContact,
  confirmContactVerification,
  deleteContact,
  fetchContacts,
  requestContactVerification,
  type VerifiedContact,
  userFacingApiError,
} from "@/lib/api-client";

const statusLabels: Record<string, string> = {
  verified: "已验证",
  pending: "等待验证",
  failed: "验证失败",
  unverified: "未验证",
};

export default function FamilyContactsPage() {
  const router = useRouter();
  const [items, setItems] = useState<VerifiedContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [channel, setChannel] = useState("phone");
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [verificationCode, setVerificationCode] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems((await fetchContacts()).items);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "联系人加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || !value.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await createContact({
        name: name.trim(),
        channel,
        value: value.trim(),
        escalation_order: items.length + 1,
        available: true,
      });
      setName("");
      setValue("");
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "联系人未保存，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(contact: VerifiedContact) {
    setBusyId(contact.id);
    setError(null);
    try {
      const result = await requestContactVerification(contact.id);
      if (result.challenge_code_dev) {
        setVerificationCode((prev) => ({ ...prev, [contact.id]: result.challenge_code_dev || "" }));
      }
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "验证请求未发出，投递状态未确认。"));
    } finally {
      setBusyId(null);
    }
  }

  async function handleConfirm(contact: VerifiedContact) {
    const code = verificationCode[contact.id]?.trim();
    if (!code) return;
    setBusyId(contact.id);
    setError(null);
    try {
      await confirmContactVerification(contact.id, code);
      setVerificationCode((prev) => ({ ...prev, [contact.id]: "" }));
      await load();
    } catch (err) {
      setError(userFacingApiError(err, "验证码未通过，请确认后重试。"));
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(contact: VerifiedContact) {
    setBusyId(contact.id);
    setError(null);
    try {
      await deleteContact(contact.id);
      setItems((prev) => prev.filter((item) => item.id !== contact.id));
    } catch (err) {
      setError(userFacingApiError(err, "删除失败，联系人仍保留。"));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <RoleShell
      role="family"
      title="已验证联系人"
    >
      <div className="product-grid lg:grid-cols-[360px_minmax(0,1fr)]">
        <form onSubmit={handleCreate} className="product-panel">
          <p className="eyebrow">联系渠道</p>
          <h2 className="section-heading">新增联系人</h2>
          <div className="mt-4 grid gap-4">
            <label className="grid gap-1 text-base font-medium text-ink">
              姓名
              <input value={name} onChange={(event) => setName(event.target.value)} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base" />
            </label>
            <label className="grid gap-1 text-base font-medium text-ink">
              联系方式
              <input value={value} onChange={(event) => setValue(event.target.value)} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base" />
            </label>
            <label className="grid gap-1 text-base font-medium text-ink">
              渠道
              <select value={channel} onChange={(event) => setChannel(event.target.value)} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base">
                <option value="phone">电话</option>
                <option value="sms">短信</option>
                <option value="email">邮件</option>
                <option value="wechat">微信</option>
              </select>
            </label>
            <button type="submit" disabled={submitting || !name.trim() || !value.trim()} className="btn-primary">
              {submitting ? "保存中" : "保存联系人"}
            </button>
          </div>
        </form>

        <section className="product-panel">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="eyebrow">已验证联系人</p>
              <h2 className="section-heading">家庭通知链路</h2>
            </div>
            {!loading && (!error || items.length > 0) && (
              <div className="metric-strip" aria-label="联系人统计">
                <div>
                  <p className="eyebrow">联系人</p>
                  <p className="text-2xl font-semibold text-ink">{items.length}</p>
                </div>
                <div>
                  <p className="eyebrow">已验证</p>
                  <p className="text-2xl font-semibold text-ink">
                    {items.filter((item) => item.verification_status === "verified").length}
                  </p>
                </div>
              </div>
            )}
          </div>
          <div className="mt-4 grid gap-3">
            <StatusBanner tone="warning" title="投递声明">
              只有服务商接受或回执确认后，页面才会显示为已验证或已投递。
            </StatusBanner>
            {loading ? (
              <LoadingState label="正在加载联系人" />
            ) : error && items.length === 0 ? (
              <ErrorState description={error} onRetry={load} />
            ) : items.length === 0 ? (
              <EmptyState title="还没有联系人" description="添加并验证至少一个联系人后，家庭照护升级链路才可用。" />
            ) : (
              <>
                {error && <ErrorState description={error} onRetry={load} />}
                {items.map((item) => (
                  <article key={item.id} className="evidence-row">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex flex-wrap gap-2">
                      <span className="rounded-full border border-status-info bg-status-info-soft px-3 py-1 text-sm text-ink">
                        {item.channel}
                      </span>
                      <span className="rounded-full border border-border bg-canvas px-3 py-1 text-sm text-ink">
                        {statusLabels[item.verification_status] || item.verification_status}
                      </span>
                    </div>
                    <h3 className="mt-3 text-lg font-semibold text-ink">{item.name}</h3>
                    <p className="mt-1 text-base leading-7 text-muted">{item.value}</p>
                    <p className="mt-1 text-sm text-muted">升级顺序：{item.escalation_order ?? "未设置"}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={busyId === item.id} onClick={() => handleVerify(item)} className="btn-secondary">
                      {busyId === item.id ? "处理中" : "请求验证"}
                    </button>
                    <button type="button" disabled={busyId === item.id} onClick={() => handleDelete(item)} className="btn-secondary border-status-critical">
                      删除
                    </button>
                  </div>
                </div>
                {item.verification_status !== "verified" && (
                  <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                    <input
                      value={verificationCode[item.id] || ""}
                      onChange={(event) => setVerificationCode((prev) => ({ ...prev, [item.id]: event.target.value }))}
                      className="min-h-11 flex-1 rounded-md border border-border bg-surface px-3 text-base"
                      inputMode="numeric"
                      placeholder="输入收到的验证码"
                    />
                    <button type="button" disabled={!verificationCode[item.id]?.trim() || busyId === item.id} onClick={() => handleConfirm(item)} className="btn-primary">
                      确认验证
                    </button>
                  </div>
                )}
                  </article>
                ))}
              </>
            )}
          </div>
        </section>
      </div>
    </RoleShell>
  );
}
