"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AlertCaseCard from "@/components/AlertCaseCard";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  acknowledgeNotification,
  ApiError,
  fetchNotifications,
  type NotificationItem,
  userFacingApiError,
} from "@/lib/api-client";

export default function FamilyAlertsPage() {
  const router = useRouter();
  const [alerts, setAlerts] = useState<NotificationItem[]>([]);
  const [status, setStatus] = useState<string>("persisted");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ackingId, setAckingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchNotifications();
      setAlerts(data.items);
      setStatus(data.status);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(
        err instanceof ApiError && err.status === 403
          ? "当前账号没有查看这位长者告警的权限。"
          : userFacingApiError(err, "告警加载失败，请稍后重试。"),
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAcknowledge(id: string) {
    setAckingId(id);
    setError(null);
    try {
      const payload = await acknowledgeNotification(id);
      if (payload.item) {
        setAlerts((prev) =>
          prev.map((item) => (item.id === payload.item?.id ? payload.item : item)),
        );
      } else {
        setAlerts((prev) =>
          prev.map((item) =>
            item.id === id ? { ...item, status: "acknowledged" } : item,
          ),
        );
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "确认失败，告警仍待处理。"));
    } finally {
      setAckingId(null);
    }
  }

  return (
    <RoleShell
      role="family"
      title="告警"
      subtitle="展示风险事件、通知状态和处理动作；未确认的投递不会写成已通知。"
    >
      <div className="grid gap-4">
        {status === "unavailable" && (
          <StatusBanner tone="warning" title="通知服务暂时不可用">
            当前无法确认通知记录。请稍后重试或联系照护运营。
          </StatusBanner>
        )}
        {error && <ErrorState description={error} onRetry={load} />}
        {loading ? (
          <LoadingState label="正在加载告警" />
        ) : alerts.length === 0 && !error ? (
          <EmptyState title="暂无告警" description="没有新的风险事件或通知记录。" />
        ) : (
          alerts.map((item) => (
            <AlertCaseCard
              key={item.id}
              item={item}
              busy={ackingId === item.id}
              onAcknowledge={() => handleAcknowledge(item.id)}
            />
          ))
        )}
      </div>
    </RoleShell>
  );
}
