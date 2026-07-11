"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { ArrowUpRight, Clock3, RadioTower, UserRoundCheck } from "lucide-react";
import PageIntro from "@/components/PageIntro";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import { ApiError, fetchOperatorCases, type OperatorCaseItem, userFacingApiError } from "@/lib/api-client";

const severityLabels: Record<string, string> = { critical: "紧急", high: "高风险", medium: "中风险", low: "低风险" };
const statusLabels: Record<string, string> = { open: "待处理", assigned: "处理中", resolved: "已解决", closed: "已关闭" };
function severityVariant(value: string): "error" | "warning" | "info" | "neutral" {
  if (value === "critical") return "error";
  if (value === "high" || !["medium", "low"].includes(value)) return "warning";
  return value === "medium" ? "info" : "neutral";
}

function nextActionFor(item: OperatorCaseItem): string {
  if (item.resolution) return "复核处置结果";
  if (item.status === "open") return item.owner_id ? "负责人接单并记录首次触达" : "分配负责人";
  if (item.status === "assigned") return "跟进照护方并补充证据";
  if (item.status === "resolved") return "确认关闭条件";
  return "查看案件证据";
}

function formatTime(value: string | null): string {
  if (!value) return "未设置";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间异常" : date.toLocaleString("zh-CN");
}

export default function OpsCarePage() {
  const router = useRouter();
  const [cases, setCases] = useState<OperatorCaseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCases((await fetchOperatorCases()).items);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(
        err instanceof ApiError && err.status === 403
          ? "当前账号不是照护运营角色。"
          : userFacingApiError(err, "照护队列加载失败，请稍后重试。"),
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  const criticalCount = cases.filter((item) => item.severity === "critical").length;
  const openCount = cases.filter((item) => item.status === "open").length;

  return (
    <RoleShell role="operator" title="照护运营" subtitle="把风险、投递异常和人工跟进变成有负责人、有时限、有证据的处置队列。">
      <div className="page-stack">
        <PageIntro
          title="安全案件"
          description="按严重度、负责人和处理时限排列。"
          action={<Button label="查看运行追踪" href="/ops/traces" variant="secondary" icon={<Icon icon={RadioTower} size="sm" />} />}
        />
        {loading ? (
          <LoadingState label="正在同步运营案件" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : (
          <>
            <div className="operator-summary" aria-label="运营案件状态">
              <span data-tone="critical"><strong>{criticalCount}</strong> 紧急</span>
              <span data-tone="warning"><strong>{openCount}</strong> 待接单</span>
              <span><strong>{cases.length}</strong> 总案件</span>
            </div>
            <p className="operator-privacy-note">仅显示处置所需的授权证据，不默认展示长者私人聊天全文。</p>
            {cases.length === 0 ? (
              <EmptyState title="暂无待处理案件" description="高风险事件或通知投递异常出现后会进入这里。" />
            ) : (
              <section className="page-stack">
                {cases.map((item) => (
                  <article key={item.id} className="operator-case-card" data-severity={item.severity}>
                    <div className="operator-case-grid">
                      <div className="operator-case-cell" style={{ minWidth: 0 }}>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                          <Badge label={severityLabels[item.severity] || "风险待确认"} variant={severityVariant(item.severity)} />
                          <Badge label={statusLabels[item.status] || item.status} variant="neutral" />
                        </div>
                        <Text display="block" size="lg" weight="semibold" style={{ marginTop: 14 }}>{item.summary || "照护案件"}</Text>
                        <Text display="block" type="code" color="secondary" style={{ marginTop: 8 }}>case {item.id}</Text>
                      </div>
                      <div className="operator-case-cell">
                        <Text display="block" type="supporting" color="secondary"><Icon icon={UserRoundCheck} size="xsm" /> 负责人</Text>
                        <Text display="block" weight="semibold" style={{ marginTop: 6 }}>{item.owner_id || "未分配"}</Text>
                        <Text display="block" type="supporting" color="secondary" style={{ marginTop: 16 }}><Icon icon={Clock3} size="xsm" /> 时限 {formatTime(item.due_at)}</Text>
                      </div>
                      <div className="operator-case-cell">
                        <Text display="block" type="supporting" color="secondary">下一步</Text>
                        <Text display="block" weight="semibold" style={{ marginTop: 8 }}>{nextActionFor(item)}</Text>
                        <Text display="block" type="code" color="secondary" style={{ marginTop: 12 }}>decision {item.safety_decision_id ? item.safety_decision_id.slice(0, 8) : "none"}</Text>
                        <Text display="block" type="code" color="secondary">outbox {item.notification_outbox_id ? item.notification_outbox_id.slice(0, 8) : "none"}</Text>
                      </div>
                      <div className="operator-case-action">
                        <Button label="查看案件" href={`/ops/care/${item.id}`} variant="secondary" endContent={<Icon icon={ArrowUpRight} size="sm" />} />
                      </div>
                    </div>
                  </article>
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </RoleShell>
  );
}
