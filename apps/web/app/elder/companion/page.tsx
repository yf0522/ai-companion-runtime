import ChatWindow from "@/components/ChatWindow";
import RoleShell from "@/components/RoleShell";

export default function ElderCompanionPage() {
  return (
    <RoleShell
      role="elder"
      title="陪伴助手"
      subtitle="先说一件最需要确认的事。系统会在执行提醒、通知或风险操作前明确说明结果。"
    >
      <ChatWindow />
    </RoleShell>
  );
}
