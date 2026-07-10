import { CheckCircle2, CircleDashed, WifiOff } from "lucide-react";

type ConnectionState =
  | "connected"
  | "connecting"
  | "reconnecting"
  | "disconnected"
  | "failed";

const labels: Record<ConnectionState, string> = {
  connected: "陪伴服务在线",
  connecting: "正在连接陪伴服务",
  reconnecting: "正在恢复连接",
  disconnected: "陪伴服务未连接",
  failed: "陪伴服务暂时不可用",
};

export default function CompanionSignal({ status }: { status: ConnectionState }) {
  const active = status === "connected";
  const pending = status === "connecting" || status === "reconnecting";
  const Icon = active ? CheckCircle2 : pending ? CircleDashed : WifiOff;

  return (
    <div className="companion-signal" role="status" aria-live="polite">
      {active ? (
        <span className="companion-signal-bars" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
        </span>
      ) : (
        <Icon size={18} className={pending ? "animate-pulse text-muted" : "text-status-critical"} />
      )}
      <span className="text-sm font-semibold text-ink">{labels[status]}</span>
    </div>
  );
}
