import { Badge } from "@astryxdesign/core/Badge";
import { Icon } from "@astryxdesign/core/Icon";
import { CircleDashed, WifiOff } from "lucide-react";

type ConnectionState = "connected" | "connecting" | "reconnecting" | "disconnected" | "failed";

const labels: Record<ConnectionState, string> = {
  connected: "陪伴服务在线",
  connecting: "正在建立安全连接",
  reconnecting: "正在恢复连接",
  disconnected: "陪伴服务未连接",
  failed: "陪伴服务暂时不可用",
};

export default function CompanionSignal({ status }: { status: ConnectionState }) {
  const active = status === "connected";
  const pending = status === "connecting" || status === "reconnecting";

  return (
    <div className="companion-signal" role="status" aria-live="polite">
      {active ? (
        <span className="companion-signal-bars" aria-hidden="true"><span /><span /><span /><span /></span>
      ) : (
        <Icon icon={pending ? CircleDashed : WifiOff} size="sm" color={pending ? "secondary" : "error"} />
      )}
      <Badge label={labels[status]} variant={active ? "teal" : pending ? "neutral" : "error"} />
    </div>
  );
}
