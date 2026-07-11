"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { HeartHandshake, MessageCircle, PhoneCall, WifiOff } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import { ApiError, fetchContacts, type VerifiedContact, userFacingApiError } from "@/lib/api-client";
import styles from "@/components/elder/ElderProduct.module.css";

function directValue(value: string): string {
  return value.replace(/[^+\d]/g, "");
}

export default function ElderHelpPage() {
  const router = useRouter();
  const [contacts, setContacts] = useState<VerifiedContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setContacts((await fetchContacts()).items);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(userFacingApiError(err, "已验证联系人暂时无法加载。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  const directContacts = useMemo(() => contacts
    .filter((contact) =>
      (contact.verification_status === "verified" || contact.verification_state === "verified") &&
      contact.available !== false &&
      contact.status !== "revoked" &&
      ["phone", "sms"].includes(contact.channel),
    )
    .sort((left, right) => (left.priority || left.escalation_order || 99) - (right.priority || right.escalation_order || 99)), [contacts]);

  return (
    <RoleShell role="elder" title="帮助">
      <div className={`${styles.pageStack} product-grid`}>
        <section className={styles.emergencyPanel}>
          <PhoneCall size={25} aria-hidden="true" />
          <div>
            <p>紧急情况</p>
            <h2>有立即危险时，直接打电话求助</h2>
            <span>严重胸痛、呼吸困难、人身危险或已经被骗转账时，不要等待系统回复，请直接联系本地紧急服务和家人。</span>
          </div>
        </section>

        <section className={styles.contactSection} aria-label="已验证联系人">
          <div className={styles.contactHeading}>
            <div>
              <p>直接联系</p>
              <h2>给信任的人打电话或发短信</h2>
              <span>这里只显示已验证且当前可用的联系方式。点击后会打开本机电话或短信，不会声称已经通知对方。</span>
            </div>
          </div>

          {loading ? (
            <LoadingState label="正在加载已验证联系人" />
          ) : error ? (
            <ErrorState title="联系人暂时不可用" description={error} onRetry={load} />
          ) : directContacts.length === 0 ? (
            <EmptyState
              title="还没有可直接联系的人"
              description="当前没有已验证并可用的电话或短信联系人。紧急情况请使用你已经知道的本地急救号码。"
            />
          ) : (
            <div className={styles.contactList}>
              {directContacts.map((contact) => {
                const value = directValue(contact.value);
                return (
                  <article className={styles.contactCard} key={contact.id}>
                    <div className={styles.contactAvatar} aria-hidden="true"><HeartHandshake size={20} /></div>
                    <div>
                      <h3>{contact.name}</h3>
                      <p>已验证 · {contact.channel === "sms" ? "短信" : "电话"}</p>
                    </div>
                    <div className={styles.contactActions}>
                      {contact.channel === "phone" && (
                        <a href={`tel:${value}`} aria-label={`打电话给${contact.name}`}><PhoneCall size={18} aria-hidden="true" />打电话</a>
                      )}
                      <a href={`sms:${value}`} aria-label={`发短信给${contact.name}`}><MessageCircle size={18} aria-hidden="true" />发短信</a>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className={styles.offlinePanel}>
          <WifiOff size={22} aria-hidden="true" />
          <div><h2>网络不可用时</h2><p>改用电话、短信或现场联系人。页面离线时，安全事项不会被错误标记为已通知。</p></div>
        </section>
        <StatusBanner tone="info" title="系统的边界">陪伴助手可以帮助理解、提醒和记录，但不会替代医生、急救人员、银行或警方。</StatusBanner>
      </div>
    </RoleShell>
  );
}
