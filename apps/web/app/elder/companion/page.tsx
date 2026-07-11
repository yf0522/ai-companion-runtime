import ChatWindow from "@/components/ChatWindow";
import RoleShell from "@/components/RoleShell";

export default function ElderCompanionPage() {
  return (
    <RoleShell
      role="elder"
      title="陪伴助手"
    >
      <ChatWindow />
    </RoleShell>
  );
}
