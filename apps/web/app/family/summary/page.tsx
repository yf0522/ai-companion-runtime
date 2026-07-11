"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, LockKeyhole, TrendingDown, TrendingUp } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import * as familyApi from "@/lib/api-client";
import type { FamilySummaryItem, FamilySummaryResponse } from "@/lib/api-client";
import FamilyPageHeader from "../_components/FamilyPageHeader";
import styles from "../family.module.css";

type SummaryRange = "7d" | "30d" | "90d";
type SummaryItem = FamilySummaryItem & {
  title?: string | null;
  owner?: string | null;
  owner_name?: string | null;
  evidence_at?: string | null;
  created_at?: string | null;
  evidence?: Record<string, unknown> | null;
};
type ProductSummary = Omit<FamilySummaryResponse, "summary"> & {
  summary: Omit<FamilySummaryResponse["summary"], "items"> & {
    range?: SummaryRange | string;
    range_start?: string | null;
    range_end?: string | null;
    denominator?: number | null;
    completion?: { completed?: number | null; rate?: number | null } | null;
    trend?: { previous_denominator?: number | null; previous_rate?: number | null; delta?: number | null; direction?: string | null } | number | null;
    completion_rate?: number | null;
    previous_completion_rate?: number | null;
    items: SummaryItem[];
  };
};
const statusLabels: Record<string, string> = {
  done: "已完成", completed: "已完成", acknowledged: "已确认", missed: "已错过", failed: "失败",
  expired: "已过期", cancelled: "已取消", snoozed: "已延后", pending: "待处理", due: "已到期",
};
const taskTypeLabels: Record<string, string> = { medication: "服药", appointment: "复诊或预约", hydration: "饮水", exercise: "运动", other: "照护任务" };
const rangeLabels: Record<SummaryRange, string> = { "7d": "最近 7 天", "30d": "最近 30 天", "90d": "最近 90 天" };
const completedStatuses = new Set(["done", "completed", "acknowledged"]);
const outlierStatuses = new Set(["missed", "failed", "expired"]);

function formatTime(value: string | null | undefined): string {
  if (!value) return "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间待确认" : date.toLocaleString("zh-CN");
}

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "未记录";
  const normalized = value <= 1 ? value * 100 : value;
  return `${Math.round(normalized)}%`;
}

function ownerLabel(value: string | null | undefined): string {
  if (!value) return "未记录";
  return { family: "家属", elder: "长者本人", operator: "照护运营", system: "服务记录", chat: "长者本人" }[value] || value;
}

export default function FamilySummaryPage() {
  const router = useRouter();
  const [range, setRange] = useState<SummaryRange>("7d");
  const [data, setData] = useState<ProductSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setData(await familyApi.fetchFamilySummary(range) as ProductSummary);
    } catch (err) {
      if (err instanceof familyApi.ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof familyApi.ApiError && err.status === 403
        ? "当前家属账号还没有获得照护摘要权限。"
        : familyApi.userFacingApiError(err, "照护摘要加载失败，请稍后重试。"));
    } finally { setLoading(false); }
  }, [range, router]);

  useEffect(() => { void load(); }, [load]);

  const summary = data?.summary;
  const denominator = summary?.denominator ?? summary?.total_outcomes ?? null;
  const completedCount = summary
    ? (summary.completion?.completed ?? Object.entries(summary.by_status || {}).reduce((total, [status, count]) => completedStatuses.has(status) ? total + count : total, 0))
      || summary.items.filter((item) => completedStatuses.has(item.status)).length
    : 0;
  const completionRate = summary?.completion?.rate ?? summary?.completion_rate ?? (denominator && denominator > 0 ? completedCount / denominator : null);
  const structuredTrend = typeof summary?.trend === "object" && summary.trend !== null ? summary.trend : null;
  const previousRate = structuredTrend?.previous_rate ?? summary?.previous_completion_rate;
  const trend = structuredTrend?.delta ?? (typeof summary?.trend === "number" ? summary.trend : null) ?? (previousRate !== null && previousRate !== undefined && completionRate !== null
    ? (completionRate <= 1 ? completionRate : completionRate / 100) - (previousRate <= 1 ? previousRate : previousRate / 100)
    : null);
  const outliers = useMemo(() => summary?.items.filter((item) => outlierStatuses.has(item.status)) || [], [summary]);
  const sortedItems = useMemo(() => [...(summary?.items || [])].sort((left, right) => {
    const leftTime = new Date(left.completed_at || left.due_at || left.created_at || 0).getTime();
    const rightTime = new Date(right.completed_at || right.due_at || right.created_at || 0).getTime();
    return rightTime - leftTime;
  }), [summary]);

  return (
    <RoleShell role="family" title="摘要">
      <div className={styles.workspace}>
        <FamilyPageHeader
          context="照护结果"
          title={`${rangeLabels[range]}发生了什么`}
          description="只汇总已授权的任务结果、错过事项和处理时间，不展示私人对话或长期记忆内容。"
        />

        <div className={styles.filterBar} role="group" aria-label="选择摘要范围">
          {(Object.keys(rangeLabels) as SummaryRange[]).map((value) => <button key={value} type="button" data-active={range === value ? "true" : "false"} onClick={() => setRange(value)}>{rangeLabels[value]}</button>)}
        </div>

        {loading ? (
          <LoadingState label="正在加载照护摘要" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : !summary || summary.total_outcomes === 0 ? (
          <EmptyState title="暂无照护结果" description={`${rangeLabels[range]}内没有完成、错过或取消的任务结果。`} />
        ) : (
          <>
            <section className={styles.summaryGrid} aria-label="照护结果统计">
              <div><dt>完成率</dt><dd>{percent(completionRate)}</dd><small>{denominator === null ? "分母未记录" : `${completedCount} / ${denominator} 项有结果的任务`}</small></div>
              <div><dt>需要回看</dt><dd>{outliers.length}</dd><small>错过、失败或过期</small></div>
              <div><dt>相较上一周期</dt><dd>{trend === null ? "未记录" : `${trend > 0 ? "+" : ""}${Math.round(trend * 100)} 个百分点`}</dd><small>{trend === null ? "服务未返回对比区间" : trend >= 0 ? "完成率上升" : "完成率下降"}</small></div>
              <div><dt>统计范围</dt><dd style={{ fontSize: 16 }}>{summary.range_start && summary.range_end ? `${formatTime(summary.range_start)} — ${formatTime(summary.range_end)}` : rangeLabels[range]}</dd><small>当前选择的明确区间</small></div>
            </section>

            <div className={styles.split}>
              <section className={styles.surface} aria-label="需要回看的照护结果">
                <div className={styles.sectionHeading}>
                  <div><h3>先看偏离计划的事项</h3><p>这些结果需要家庭确认是否重新安排或补充说明。</p></div>
                  {trend !== null && (trend >= 0 ? <TrendingUp color="var(--care-success)" /> : <TrendingDown color="var(--care-critical)" />)}
                </div>
                {outliers.length === 0 ? (
                  <p className={styles.empty} style={{ marginTop: 16 }}><strong>没有需要回看的异常结果</strong>这个区间内没有记录错过、失败或过期。</p>
                ) : (
                  <div className={styles.outcomeList} style={{ marginTop: 18 }}>
                    {outliers.map((item) => (
                      <article key={`${item.task_id}-${item.status}`} className={styles.outcomeCard} data-tone="critical">
                        <div><h4>{item.title || taskTypeLabels[item.task_type] || "照护任务"}</h4><p>{statusLabels[item.status] || "状态待确认"} · 负责人：{ownerLabel(item.owner_name || item.owner)}</p></div>
                        <time>{formatTime(item.evidence_at || item.completed_at || item.due_at)}</time>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <aside className={styles.surfaceSoft} aria-label="摘要证据说明">
                <div className={styles.relationLine}><LockKeyhole size={20} /><h3>证据边界</h3></div>
                <p className={styles.surfaceLead}>每一项只引用任务名称、结果、负责人和发生时间。没有任务证据时显示“未记录”，不会用聊天内容补全。</p>
                <div className={styles.metaLine} style={{ marginTop: 14 }}><span><CalendarDays size={15} /> {rangeLabels[range]}</span><span>结果分母：{denominator ?? "未记录"}</span></div>
              </aside>
            </div>

            <section className={styles.surface} aria-label="照护结果历史">
              <div className={styles.sectionHeading}><div><h3>照护结果历史</h3><p>按最近发生时间排列，可回看状态与责任记录。</p></div></div>
              <div className={styles.outcomeList} style={{ marginTop: 18 }}>
                {sortedItems.map((item) => (
                  <article key={`${item.task_id}-${item.status}-${item.completed_at || item.due_at}`} className={styles.outcomeCard} data-tone={outlierStatuses.has(item.status) ? "critical" : "neutral"}>
                    <div><h4>{item.title || taskTypeLabels[item.task_type] || "照护任务"}</h4><p>{statusLabels[item.status] || "状态待确认"} · 负责人：{ownerLabel(item.owner_name || item.owner)}</p></div>
                    <time>{formatTime(item.evidence_at || item.completed_at || item.due_at)}</time>
                  </article>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
