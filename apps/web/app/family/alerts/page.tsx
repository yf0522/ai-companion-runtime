"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  acknowledgeNotification,
  ApiError,
  fetchNotifications,
  userFacingApiError,
} from "@/lib/api-client";
import FamilyAlertCard, { type FamilyNotificationItem } from "../_components/FamilyAlertCard";
import FamilyPageHeader from "../_components/FamilyPageHeader";
import styles from "../family.module.css";

type AlertFilter = "open" | "acknowledged" | "all";
const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

function isAcknowledged(item: FamilyNotificationItem): boolean {
  return item.status === "acknowledged" || Boolean(item.acknowledged_at);
}

function FamilyAlertsWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [alerts, setAlerts] = useState<FamilyNotificationItem[]>([]);
  const [status, setStatus] = useState<string>("persisted");
  const [filter, setFilter] = useState<AlertFilter>("open");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ackingId, setAckingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchNotifications();
      setAlerts(data.items as FamilyNotificationItem[]);
      setStatus(data.status);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof ApiError && err.status === 403
        ? "当前账号没有查看这位长者告警的权限。"
        : userFacingApiError(err, "告警加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  async function handleAcknowledge(id: string) {
    setAckingId(id);
    setError(null);
    try {
      const payload = await acknowledgeNotification(id);
      setAlerts((prev) => prev.map((item) => item.id === id
        ? (payload.item as FamilyNotificationItem | undefined) || { ...item, status: "acknowledged" }
        : item));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(userFacingApiError(err, "确认失败，告警仍待处理。"));
    } finally {
      setAckingId(null);
    }
  }

  const focusId = searchParams.get("focus");
  const visibleAlerts = useMemo(() => alerts
    .filter((item) => filter === "all" || (filter === "open" ? !isAcknowledged(item) : isAcknowledged(item)))
    .sort((left, right) => {
      if (left.id === focusId) return -1;
      if (right.id === focusId) return 1;
      if (isAcknowledged(left) !== isAcknowledged(right)) return isAcknowledged(left) ? 1 : -1;
      const severity = (severityOrder[left.severity] ?? 1.5) - (severityOrder[right.severity] ?? 1.5);
      if (severity) return severity;
      return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
    }), [alerts, filter, focusId]);
  const openCount = alerts.filter((item) => !isAcknowledged(item)).length;

  return (
    <RoleShell role="family" title="告警">
      <div className={styles.workspace}>
        <FamilyPageHeader
          context="风险与确认"
          title={openCount > 0 ? `有 ${openCount} 件事情等待确认` : "目前没有待确认的告警"}
          description="先看未处理事项；投递、查看和人工确认是不同状态，只展示服务实际记录。"
        />

        {status === "unavailable" && (
          <div className={styles.notice} data-tone="warning" role="status">
            <strong>通知服务暂时不可用</strong>
            当前无法确认通知记录。这不是“暂无告警”，请稍后重试或联系照护运营。
          </div>
        )}

        <div className={styles.filterBar} role="group" aria-label="筛选告警">
          {([
            ["open", `待确认 ${openCount}`],
            ["acknowledged", `已确认 ${alerts.length - openCount}`],
            ["all", `全部 ${alerts.length}`],
          ] as const).map(([value, label]) => (
            <button key={value} type="button" data-active={filter === value ? "true" : "false"} onClick={() => setFilter(value)}>{label}</button>
          ))}
        </div>

        {loading ? (
          <LoadingState label="正在加载告警" />
        ) : error && alerts.length === 0 ? (
          <ErrorState description={error} onRetry={load} />
        ) : status === "unavailable" && alerts.length === 0 ? null : visibleAlerts.length === 0 ? (
          <EmptyState title={filter === "open" ? "暂无告警" : "这个筛选下还没有记录"} description={filter === "open" ? "没有新的风险事件需要确认。" : "切换筛选可以查看其他告警状态。"} />
        ) : (
          <section className={styles.stack} aria-label="告警记录">
            {error && <ErrorState description={error} onRetry={load} />}
            {visibleAlerts.map((item) => (
              <FamilyAlertCard
                key={item.id}
                item={item}
                busy={ackingId === item.id}
                onAcknowledge={() => handleAcknowledge(item.id)}
                contactHref="/family/contacts"
              />
            ))}
          </section>
        )}

        {!loading && !error && alerts.length > 0 && (
          <section className="metric-strip" aria-label="告警统计">
            <div><p className="eyebrow">待确认</p><p className="text-2xl font-semibold text-ink">{openCount}</p></div>
            <div><p className="eyebrow">已确认</p><p className="text-2xl font-semibold text-ink">{alerts.length - openCount}</p></div>
          </section>
        )}
      </div>
    </RoleShell>
  );
}

export default function FamilyAlertsPage() {
  return (
    <Suspense fallback={(
      <RoleShell role="family" title="风险告警">
        <LoadingState label="正在加载告警" />
      </RoleShell>
    )}>
      <FamilyAlertsWorkspace />
    </Suspense>
  );
}
