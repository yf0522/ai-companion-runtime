import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { ArrowUpRight, Clock3, PhoneCall, RadioTower, ShieldAlert } from "lucide-react";
import type { NotificationItem } from "@/lib/api-client";

const categoryLabel: Record<string, string> = { scam_alert: "诈骗风险", emotional_low: "情绪关怀", health_emergency: "健康风险", none: "照护提醒" };
const statusLabel: Record<string, string> = { pending: "等待投递", queued: "已排队", sent: "已发送", delivered: "已送达", read: "已读", failed: "投递失败", acknowledged: "已确认" };

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function severityVariant(severity: string): "error" | "warning" | "info" {
  if (severity === "critical" || severity === "high") return "error";
  return severity === "low" ? "info" : "warning";
}

function statusVariant(status: string): "success" | "warning" | "error" | "neutral" {
  if (status === "delivered" || status === "read" || status === "acknowledged") return "success";
  if (status === "failed") return "error";
  if (status === "pending" || status === "queued") return "warning";
  return "neutral";
}

function statusSteps(status: string): string[] {
  if (status === "acknowledged") return ["风险已记录", "已送达家人", "已确认处理"];
  if (status === "read") return ["风险已记录", "家人已查看", "尚未确认处理"];
  if (status === "delivered") return ["风险已记录", "已送达家人", "尚未确认处理"];
  if (status === "failed") return ["风险已记录", "通知未送达", "需要人工联系"];
  return ["风险已记录", statusLabel[status] || "投递待确认", "尚未确认处理"];
}

export default function AlertCaseCard({
  item,
  onAcknowledge,
  busy,
  showTraceLink = false,
  featured = false,
  primaryHref,
  secondaryHref,
}: {
  item: NotificationItem;
  onAcknowledge?: () => void;
  busy?: boolean;
  showTraceLink?: boolean;
  featured?: boolean;
  primaryHref?: string;
  secondaryHref?: string;
}) {
  const actionsVisible = Boolean(primaryHref || secondaryHref || showTraceLink || (onAcknowledge && item.status !== "acknowledged"));

  return (
    <article className={featured ? "attention-card" : "care-card alert-card"} data-severity={item.severity}>
      <div className="attention-card-layout">
        {featured && <div className="attention-card-icon" aria-hidden="true"><ShieldAlert size={28} /></div>}
        <div className="attention-card-copy">
          <div className="attention-card-badges">
            <Badge label={categoryLabel[item.category] || "照护告警"} variant={severityVariant(item.severity)} />
            {!featured && <Badge label={statusLabel[item.status] || "状态待确认"} variant={statusVariant(item.status)} />}
          </div>
          <h3>{item.title}</h3>
          <Text display="block" color="secondary" className="attention-card-message">{item.message}</Text>

          {featured ? (
            <div className="attention-card-steps" aria-label="告警处理状态">
              {statusSteps(item.status).map((step, index) => <span key={step} data-current={index === 2 && item.status !== "acknowledged" ? "true" : "false"}>{step}</span>)}
            </div>
          ) : (
            <div className="attention-card-meta">
              <Text type="supporting" color="secondary"><Icon icon={Clock3} size="xsm" /> {formatTime(item.created_at)}</Text>
              {showTraceLink && item.trace_id && <Text type="code" color="secondary">trace {item.trace_id.slice(0, 10)}</Text>}
            </div>
          )}
        </div>

        {actionsVisible && (
          <div className="attention-card-actions">
            {primaryHref && <Button label="查看并处理" href={primaryHref} variant="primary" endContent={<Icon icon={ArrowUpRight} size="sm" />} />}
            {secondaryHref && <Button label="联系本人" href={secondaryHref} variant="secondary" icon={<Icon icon={PhoneCall} size="sm" />} />}
            {showTraceLink && item.trace_id && <Button label="查看追踪" href={`/ops/traces/${item.trace_id}`} variant="secondary" icon={<Icon icon={RadioTower} size="sm" />} />}
            {onAcknowledge && item.status !== "acknowledged" && <Button label={busy ? "确认中" : "确认已处理"} variant="primary" isLoading={busy} onClick={onAcknowledge} endContent={<Icon icon={ArrowUpRight} size="sm" />} />}
          </div>
        )}
      </div>
    </article>
  );
}
