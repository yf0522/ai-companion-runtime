import RoleShell from "@/components/RoleShell";
import { StatusBanner } from "@/components/SurfaceStates";

export default function ElderHelpPage() {
  return (
    <RoleShell
      role="elder"
      title="帮助"
      subtitle="需要帮助时，优先联系家人或本地紧急服务；系统不会替代急救。"
    >
      <div className="grid gap-4">
        <StatusBanner tone="critical" title="紧急情况">
          如果有立即的人身危险、严重胸痛、呼吸困难或已经被骗转账，请直接拨打本地紧急电话。
        </StatusBanner>
        <StatusBanner tone="info" title="联系家人">
          可以在陪伴对话中说“我需要联系家人”。系统会说明哪些投递状态已经确认，哪些仍未确认。
        </StatusBanner>
        <StatusBanner tone="offline" title="网络不可用">
          如果页面显示未连接，请改用电话、短信或现场联系人。安全事项不会因为页面离线而被标记为已通知。
        </StatusBanner>
      </div>
    </RoleShell>
  );
}
