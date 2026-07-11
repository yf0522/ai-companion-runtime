import RoleShell from "@/components/RoleShell";
import { StatusBanner } from "@/components/SurfaceStates";
import { HeartHandshake, PhoneCall, WifiOff } from "lucide-react";

export default function ElderHelpPage() {
  return (
    <RoleShell
      role="elder"
      title="帮助"
    >
      <div className="product-grid">
        <section className="rounded-lg border border-status-critical bg-status-critical-soft p-5">
          <PhoneCall size={24} className="text-status-critical" />
          <h2 className="mt-3 text-xl font-bold text-ink">有立即危险时，直接打电话求助</h2>
          <p className="mt-2 text-lg leading-8 text-ink">严重胸痛、呼吸困难、人身危险或已经被骗转账时，不要等待系统回复，请直接联系本地紧急服务和家人。</p>
        </section>
        <div className="grid gap-4 md:grid-cols-2">
          <section className="product-panel">
            <HeartHandshake size={22} className="text-primary-strong" />
            <h2 className="mt-3 section-heading">联系家人</h2>
            <p className="mt-2 text-base leading-7 text-muted">在陪伴对话中说“我需要联系家人”。系统会明确说明通知是否送达，而不是只显示“已发送”。</p>
          </section>
          <section className="product-panel">
            <WifiOff size={22} className="text-muted" />
            <h2 className="mt-3 section-heading">网络不可用</h2>
            <p className="mt-2 text-base leading-7 text-muted">改用电话、短信或现场联系人。页面离线时，安全事项不会被错误标记为已通知。</p>
          </section>
        </div>
        <StatusBanner tone="info" title="系统的边界">陪伴助手可以帮助理解、提醒和记录，但不会替代医生、急救人员、银行或警方。</StatusBanner>
      </div>
    </RoleShell>
  );
}
