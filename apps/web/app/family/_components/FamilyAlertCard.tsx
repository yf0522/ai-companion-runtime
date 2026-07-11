import { BellRing, CheckCircle2, Clock3, ExternalLink, PhoneCall, UserRound } from "lucide-react";
import type { NotificationItem } from "@/lib/api-client";
import styles from "../family.module.css";

export interface DeliveryEvent {
  id?: string;
  event_type?: string;
  status?: string;
  actor_name?: string | null;
  actor?: string | null;
  occurred_at?: string | null;
  created_at?: string | null;
  evidence_href?: string | null;
}

export type FamilyNotificationItem = NotificationItem & {
  delivery_status?: string | null;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  acknowledged_by_name?: string | null;
  owner_id?: string | null;
  owner_name?: string | null;
  evidence_href?: string | null;
  delivery_events?: DeliveryEvent[];
  receipts?: DeliveryEvent[];
  events?: DeliveryEvent[];
  delivery?: {
    state?: string | null;
    provider?: string | null;
    channel?: string | null;
    attempt_count?: number | null;
    last_error?: string | null;
    updated_at?: string | null;
  } | null;
  evidence?: {
    operator_case_id?: string | null;
    safety_decision_id?: string | null;
    trace_id?: string | null;
    ack_actor_type?: string | null;
  } | null;
};

const categoryLabels: Record<string, string> = {
  scam_alert: "诈骗风险",
  emotional_low: "情绪关怀",
  health_emergency: "健康风险",
  none: "照护提醒",
};

const deliveryLabels: Record<string, string> = {
  pending: "等待投递",
  queued: "等待投递",
  accepted: "服务已接受",
  sent: "已发送",
  delivered: "已送达",
  read: "已读",
  failed: "投递失败",
  expired: "投递已过期",
  unknown: "投递待确认",
  unconfigured: "尚未配置投递",
  acknowledged: "已确认",
};

function formatTime(value: string | null | undefined): string {
  if (!value) return "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间待确认" : date.toLocaleString("zh-CN");
}

function alertTone(item: FamilyNotificationItem): "critical" | "warning" | "info" {
  if (item.severity === "critical" || item.severity === "high") return "critical";
  if (item.severity === "low") return "info";
  return "warning";
}

export function notificationEvents(item: FamilyNotificationItem): DeliveryEvent[] {
  const events = item.delivery_events || item.receipts || item.events || [];
  return [...events].sort((left, right) => {
    const leftTime = Date.parse(left.occurred_at || left.created_at || "");
    const rightTime = Date.parse(right.occurred_at || right.created_at || "");
    if (Number.isNaN(leftTime)) return Number.isNaN(rightTime) ? 0 : 1;
    if (Number.isNaN(rightTime)) return -1;
    return leftTime - rightTime;
  });
}

export function notificationState(item: FamilyNotificationItem): string {
  return item.delivery?.state || item.delivery_status || item.status || "unknown";
}

export default function FamilyAlertCard({
  item,
  featured = false,
  busy = false,
  onAcknowledge,
  primaryHref,
  contactHref,
}: {
  item: FamilyNotificationItem;
  featured?: boolean;
  busy?: boolean;
  onAcknowledge?: () => void;
  primaryHref?: string;
  contactHref?: string;
}) {
  const events = notificationEvents(item);
  const deliveryState = notificationState(item);
  const acknowledged = item.status === "acknowledged" || Boolean(item.acknowledged_at);
  const tone = alertTone(item);
  const owner = item.owner_name || (item.owner_id ? `负责人 ${item.owner_id.slice(0, 8)}` : null);
  const cardClass = featured ? `attention-card ${styles.featuredAlert}` : styles.alertCard;

  return (
    <article className={cardClass} data-severity={item.severity} data-tone={tone}>
      <div className={styles.alertHeading}>
        <div className={styles.alertIcon} aria-hidden="true"><BellRing size={featured ? 26 : 20} /></div>
        <div>
          <div className={styles.inlineStates}>
            <span className={styles.statePill} data-tone={tone}>{categoryLabels[item.category] || "照护告警"}</span>
            <span className={styles.statePill} data-tone={acknowledged ? "success" : deliveryState === "failed" ? "critical" : "neutral"}>
              {acknowledged ? "已确认" : deliveryLabels[deliveryState] || "投递待确认"}
            </span>
          </div>
          <h3>{item.title}</h3>
          <p>{item.message}</p>
        </div>
      </div>

      <dl className={styles.factGrid}>
        <div>
          <dt><Clock3 size={16} />风险记录</dt>
          <dd>{formatTime(item.created_at)}</dd>
        </div>
        <div>
          <dt><UserRound size={16} />下一步负责人</dt>
          <dd>{owner || (acknowledged ? "已由家属确认" : "尚未指定")}</dd>
        </div>
        <div>
          <dt><CheckCircle2 size={16} />人工确认</dt>
          <dd>{acknowledged ? `${item.acknowledged_by_name || item.acknowledged_by || "家属"} · ${formatTime(item.acknowledged_at)}` : "尚未确认处理"}</dd>
        </div>
      </dl>

      <div className={styles.cardActions}>
        {primaryHref && <a className="btn-primary" href={primaryHref}>查看并处理</a>}
        {contactHref && <a className="btn-secondary" href={contactHref}><PhoneCall size={16} /> 联系本人</a>}
        {item.evidence_href && <a className="btn-secondary" href={item.evidence_href}>查看授权证据</a>}
        {onAcknowledge && !acknowledged && (
          <button type="button" className="btn-primary" disabled={busy} onClick={onAcknowledge}>
            {busy ? "确认中" : "确认已接手"}
          </button>
        )}
      </div>

      <section className={styles.timeline} aria-label="真实投递与确认记录">
        <h4>投递与确认记录</h4>
        {events.length > 0 ? (
          <ol>
            {events.map((event, index) => {
              const state = event.event_type || event.status || "unknown";
              return (
                <li key={event.id || `${state}-${index}`}>
                  <strong>{deliveryLabels[state] || state}</strong>
                  <span>{event.actor_name || event.actor || "服务记录"}</span>
                  <time>{formatTime(event.occurred_at || event.created_at)}</time>
                  {event.evidence_href && <a href={event.evidence_href}>查看授权证据 <ExternalLink size={14} /></a>}
                </li>
              );
            })}
          </ol>
        ) : (
          <p>
            暂无逐条投递回执；目前可确认的投递状态是“{deliveryLabels[deliveryState] || "状态待确认"}”。
            {item.delivery?.provider ? `（${item.delivery.provider} · ${item.delivery.channel || "渠道未记录"} · 尝试 ${item.delivery.attempt_count ?? "未记录"} 次）` : ""}，
            不会据此推断家人已经查看或处理。
            {item.delivery?.last_error ? ` 最近失败原因：${item.delivery.last_error}` : ""}
          </p>
        )}
      </section>
    </article>
  );
}
