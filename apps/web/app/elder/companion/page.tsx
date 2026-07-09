import ChatWindow from "@/components/ChatWindow";
import RoleShell from "@/components/RoleShell";

export default function ElderCompanionPage() {
  return (
    <RoleShell
      role="elder"
      title="陪伴"
      subtitle="用对话确认今日事项、设置提醒、说明风险，或请求联系家人。"
    >
      <ChatWindow />
    </RoleShell>
  );
}
