"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Search, ShieldCheck } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchTraces,
  type TraceListItem,
  userFacingApiError,
} from "@/lib/api-client";
import {
  formatRecordedMetric,
  isFailedTraceStatus,
  operatorSeverityLabel,
  operatorStatusLabel,
  traceStatusLabel,
} from "../_lib/operator";
import styles from "../operator.module.css";

type TraceFilter = "all" | "failed" | "completed" | "unknown";

function statusTone(status: string): "critical" | "success" | "neutral" {
  if (isFailedTraceStatus(status)) return "critical";
  if (["completed", "success"].includes(status)) return "success";
  return "neutral";
}

function formatTime(value: string | null): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间待确认" : date.toLocaleString("zh-CN");
}

export default function OpsTracesPage() {
  const router = useRouter();
  const [items, setItems] = useState<TraceListItem[]>([]);
  const [scope, setScope] = useState<string>("operator_case");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<TraceFilter>("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchTraces(100, 0);
      setItems(data.items);
      setScope(data.scope);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "追踪列表加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  const visibleItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return items.filter((item) => {
      const failed = isFailedTraceStatus(item.status);
      if (filter === "failed" && !failed) return false;
      if (filter === "completed" && !["completed", "success"].includes(item.status)) return false;
      if (filter === "unknown" && item.status !== "unknown") return false;
      if (!normalizedQuery) return true;
      return [item.trace_id, item.case_id, item.user_id]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery));
    });
  }, [filter, items, query]);

  const failedCount = items.filter((item) => isFailedTraceStatus(item.status)).length;
  const unknownCount = items.filter((item) => item.status === "unknown").length;
  const linkedCases = new Set(items.flatMap((item) => item.case_ids || [])).size;

  return (
    <RoleShell role="operator" title="运行追踪" subtitle="仅展示案件授权范围内的运行证据">
      <div className={styles.workspace}>
        <header className={styles.pageHeader}>
          <div>
            <h2>案件追踪证据</h2>
            <p>运营账号只能查看与安全案件关联的 Trace；打开详情会写入案件审计时间线。</p>
          </div>
          <span className={styles.badge} data-tone={scope === "operator_case" ? "success" : "warning"}><ShieldCheck size={14} /> {scope === "operator_case" ? "案件授权范围" : "权限范围待确认"}</span>
        </header>

        {loading ? (
          <LoadingState label="正在加载案件追踪" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : (
          <>
            <section className={styles.summaryStrip} aria-label="追踪状态统计">
              <div><span>可查看追踪</span><strong>{items.length}</strong></div>
              <div><span>失败或超时</span><strong>{failedCount}</strong></div>
              <div><span>状态未记录</span><strong>{unknownCount}</strong></div>
              <div><span>关联案件</span><strong>{linkedCases}</strong></div>
            </section>

            <section className={`${styles.toolbar} ${styles.toolbarCompact}`} aria-label="追踪筛选">
              <label className={styles.searchControl}>
                <span className="sr-only">搜索追踪</span>
                <Search className={styles.searchIcon} size={16} aria-hidden="true" />
                <input className={`${styles.searchField} ${styles.searchFieldWithIcon}`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Trace、案件或用户 ID" />
              </label>
              <div className={styles.filterGroup}>
                <label htmlFor="trace-filter">状态</label>
                <select id="trace-filter" className={styles.selectField} value={filter} onChange={(event) => setFilter(event.target.value as TraceFilter)}>
                  <option value="all">全部</option>
                  <option value="failed">失败或超时</option>
                  <option value="completed">已完成</option>
                  <option value="unknown">未记录</option>
                </select>
              </div>
            </section>

            {visibleItems.length === 0 ? (
              <EmptyState title={items.length === 0 ? "暂无案件授权追踪" : "没有符合筛选条件的追踪"} description={items.length === 0 ? "安全案件关联运行证据后才会出现在这里。" : "调整搜索或状态条件后重试。"} />
            ) : (
              <section className={styles.traceList} aria-label="追踪列表">
                {visibleItems.map((item) => (
                  <article key={item.trace_id} className={styles.traceRow}>
                    <div>
                      <div className={styles.traceId}>{item.trace_id}</div>
                      <span className={styles.cellHint}>{formatTime(item.started_at)}</span>
                    </div>
                    <div className={styles.badgeRow}>
                      <span className={styles.badge} data-tone={statusTone(item.status)}>{traceStatusLabel(item.status)}</span>
                    </div>
                    <div>
                      <strong>{formatRecordedMetric(item.event_count)} 个事件</strong>
                      <div className={styles.cellHint}>{item.failed_event_count == null ? "失败数未记录" : `${item.failed_event_count} 个失败步骤`}</div>
                    </div>
                    <div>
                      <strong>{operatorSeverityLabel(item.severity)}</strong>
                      <div className={styles.cellHint}>{operatorStatusLabel(item.case_status)} · 案件 {item.case_id ? `${item.case_id.slice(0, 8)}…` : "未关联"}</div>
                    </div>
                    <div className={styles.rowAction}>
                      <a className={styles.compactButton} href={`/ops/traces/${item.trace_id}`}>查看 <ArrowUpRight size={14} /></a>
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
