"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { ArrowUpRight, BellRing, ClipboardCheck, LockKeyhole } from "lucide-react";
import AlertCaseCard from "@/components/AlertCaseCard";
import CareTaskCard from "@/components/CareTaskCard";
import PageIntro from "@/components/PageIntro";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import { ApiError, fetchNotifications, fetchCareTasks, type NotificationItem, type CareTaskItem, userFacingApiError } from "@/lib/api-client";

export default function FamilyOverviewPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<CareTaskItem[]>([]);
  const [alerts, setAlerts] = useState<NotificationItem[]>([]);
  const [notificationStatus, setNotificationStatus] = useState("persisted");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [taskData, notificationData] = await Promise.all([fetchCareTasks(), fetchNotifications()]);
      setTasks(taskData); setAlerts(notificationData.items); setNotificationStatus(notificationData.status);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof ApiError && err.status === 403 ? "当前家属账号还没有绑定可查看的长者。" : userFacingApiError(err, "家属概览加载失败，请稍后重试。"));
    } finally { setLoading(false); }
  }, [router]);
  useEffect(() => { load(); }, [load]);

  const openAlerts = alerts.filter((item) => item.status !== "acknowledged");
  const activeTasks = tasks.filter((task) => !["completed", "cancelled", "archived", "expired"].includes(task.status || "")).slice(0, 3);

  return (
    <RoleShell role="family" title="家庭照护" subtitle="只看需要关注的结果、真实投递状态和下一步，不展示长者私人对话。">
      <div className="page-stack">
        <PageIntro kicker="FAMILY CARE PULSE" title={openAlerts.length ? `${openAlerts.length} 件事情需要你关注` : "家里目前没有未处理异常"} description="Companion 会把风险、未确认事项和投递结果收敛成可行动的家庭照护流。" action={<Button label="管理照护任务" href="/family/tasks" variant="primary" icon={<Icon icon={ClipboardCheck} size="sm" />} />} />

        <div className="metric-strip" aria-label="家庭照护状态">
          <div><Badge label="异常" variant={openAlerts.length ? "error" : "success"} /><Text display="block" size="3xl" weight="semibold" hasTabularNumbers style={{ marginTop: 10 }}>{openAlerts.length}</Text><Text type="supporting" color="secondary">尚未确认的告警</Text></div>
          <div><Badge label="照护节奏" variant="cyan" /><Text display="block" size="3xl" weight="semibold" hasTabularNumbers style={{ marginTop: 10 }}>{activeTasks.length}</Text><Text type="supporting" color="secondary">正在进行的任务</Text></div>
          <div><Badge label="隐私" variant="neutral" /><Text display="block" weight="semibold" style={{ marginTop: 12 }}><Icon icon={LockKeyhole} size="sm" /> 结果可见，对话默认不可见</Text><Text type="supporting" color="secondary">按授权范围呈现</Text></div>
        </div>

        {notificationStatus === "unavailable" && <StatusBanner tone="warning" title="通知状态暂时不可用">这不是暂无告警。请稍后重试，或联系照护运营确认投递情况。</StatusBanner>}
        {loading ? <LoadingState label="正在同步家庭照护状态" /> : error ? <ErrorState description={error} onRetry={load} /> : (
          <>
            <section className="page-stack">
              <PageIntro kicker="NEEDS ATTENTION" title="需要关注" description="先处理异常，再安排日常事项。每条告警都显示真实投递状态。" tone={openAlerts.length ? "red" : "teal"} action={<Button label="查看全部告警" href="/family/alerts" variant="secondary" icon={<Icon icon={BellRing} size="sm" />} />} />
              {openAlerts.length === 0 ? <EmptyState title="暂无需要处理的告警" description="通知记录会区分排队、发送、送达、失败和已确认。" /> : openAlerts.slice(0, 2).map((item) => <AlertCaseCard key={item.id} item={item} />)}
            </section>

            <section className="page-stack">
              <PageIntro kicker="CARE RHYTHM" title="接下来的照护任务" description="只展示仍在进行、等待确认或即将触发的任务。" action={<Button label="打开任务中心" href="/family/tasks" variant="ghost" endContent={<Icon icon={ArrowUpRight} size="sm" />} />} />
              {activeTasks.length === 0 ? <EmptyState title="暂无进行中的照护任务" description="创建任务时请说明内容、日期、时间和重复计划。" /> : activeTasks.map((task) => <CareTaskCard key={task.id} task={task} />)}
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
