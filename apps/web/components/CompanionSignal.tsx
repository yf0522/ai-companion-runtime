import { CircleDashed, WifiOff } from "lucide-react";

type ConnectionState = "connected" | "connecting" | "reconnecting" | "disconnected" | "failed";

const labels: Record<ConnectionState, string> = {
  connected: "可以开始说了",
  connecting: "正在连接陪伴服务",
  reconnecting: "正在恢复连接",
  disconnected: "当前未连接",
  failed: "陪伴服务暂时不可用",
};

export default function CompanionSignal({ status }: { status: ConnectionState }) {
  const active = status === "connected";
  const pending = status === "connecting" || status === "reconnecting";

  return (
    <div className="companion-signal" data-state={status} role="status" aria-live="polite">
      {active ? (
        <span className="companion-status-dot" aria-hidden="true" />
      ) : pending ? (
        <CircleDashed size={17} aria-hidden="true" />
      ) : (
        <WifiOff size={17} aria-hidden="true" />
      )}
      <span>{labels[status]}</span>
    </div>
  );
}
