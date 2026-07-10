import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { ArrowUpRight, Clock3, RadioTower } from "lucide-react";
import type { NotificationItem } from "@/lib/api-client";

const categoryLabel: Record<string, string> = { scam_alert: "诈骗风险", emotional_low: "情绪关怀", health_emergency: "健康风险", none: "照护提醒" };
const statusLabel: Record<string, string> = { pending: "等待投递", queued: "已排队", sent: "已发送", delivered: "已送达", read: "已读", failed: "投递失败", acknowledged: "已确认" };

function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN"); }
function severityVariant(severity: string): "error" | "warning" | "info" { return severity === "critical" || severity === "high" ? "error" : severity === "medium" ? "warning" : "info"; }
function statusVariant(status: string): "success" | "warning" | "error" | "neutral" { if (status === "delivered" || status === "read" || status === "acknowledged") return "success"; if (status === "failed") return "error"; if (status === "pending" || status === "queued") return "warning"; return "neutral"; }

export default function AlertCaseCard({ item, onAcknowledge, busy, showTraceLink = false }: { item: NotificationItem; onAcknowledge?: () => void; busy?: boolean; showTraceLink?: boolean; }) {
  return (
    <article className="care-card">
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 20, alignItems: "start" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <Badge label={categoryLabel[item.category] || "照护告警"} variant={severityVariant(item.severity)} />
            <Badge label={statusLabel[item.status] || "状态待确认"} variant={statusVariant(item.status)} />
          </div>
          <h3 style={{ margin: "14px 0 0", fontSize: 20, lineHeight: 1.3 }}>{item.title}</h3>
          <Text display="block" color="secondary" style={{ marginTop: 7, lineHeight: 1.65 }}>{item.message}</Text>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginTop: 14 }}>
            <Text type="supporting" color="secondary"><Icon icon={Clock3} size="xsm" /> {formatTime(item.created_at)}</Text>
            {item.trace_id && <Text type="code" color="secondary">trace {item.trace_id.slice(0, 10)}</Text>}
          </div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" }}>
          {showTraceLink && item.trace_id && <Button label="查看追踪" href={`/ops/traces/${item.trace_id}`} variant="secondary" icon={<Icon icon={RadioTower} size="sm" />} />}
          {onAcknowledge && item.status !== "acknowledged" && <Button label={busy ? "确认中" : "确认已处理"} variant="primary" isLoading={busy} onClick={onAcknowledge} endContent={<Icon icon={ArrowUpRight} size="sm" />} />}
        </div>
      </div>
    </article>
  );
}
