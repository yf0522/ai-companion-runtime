import Link from "next/link";
import type { NotificationItem } from "@/lib/api-client";

const categoryLabel: Record<string, string> = {
  scam_alert: "诈骗风险",
  emotional_low: "情绪关怀",
  health_emergency: "健康风险",
  none: "照护提醒",
};

const statusLabel: Record<string, string> = {
  pending: "等待投递",
  queued: "已排队",
  sent: "已发送",
  delivered: "已送达",
  read: "已读",
  failed: "投递失败",
  acknowledged: "已确认",
};

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}

function severityTone(severity: string): string {
  if (severity === "critical" || severity === "high") {
    return "border-status-critical bg-status-critical-soft text-ink";
  }
  if (severity === "medium") {
    return "border-status-warning bg-status-warning-soft text-ink";
  }
  return "border-status-info bg-status-info-soft text-ink";
}

export default function AlertCaseCard({
  item,
  onAcknowledge,
  busy,
  showTraceLink = false,
}: {
  item: NotificationItem;
  onAcknowledge?: () => void;
  busy?: boolean;
  showTraceLink?: boolean;
}) {
  return (
    <article className="care-card">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap gap-2">
            <span className={`status-pill ${severityTone(item.severity)}`}>
              {categoryLabel[item.category] || "照护告警"}
            </span>
            <span className="status-pill border-border bg-canvas text-ink">
              {statusLabel[item.status] || "状态待确认"}
            </span>
          </div>
          <h3 className="mt-3 text-lg font-semibold text-ink">{item.title}</h3>
          <p className="mt-1 max-w-3xl text-base leading-7 text-muted">
            {item.message}
          </p>
          <p className="mt-2 text-sm text-muted">
            记录时间：{formatTime(item.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 sm:justify-end">
          {showTraceLink && item.trace_id && (
            <Link href={`/ops/traces/${item.trace_id}`} className="btn-secondary">
              查看追踪
            </Link>
          )}
          {onAcknowledge && item.status !== "acknowledged" && (
            <button
              type="button"
              disabled={busy}
              onClick={onAcknowledge}
              className="btn-primary"
            >
              {busy ? "确认中" : "确认已处理"}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
