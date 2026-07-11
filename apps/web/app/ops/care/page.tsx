"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, Clock3, Search, UserRoundCheck } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchOperatorCases,
  type OperatorCaseItem,
  userFacingApiError,
} from "@/lib/api-client";
import {
  caseMatchesFilter,
  caseOwnerLabel,
  caseSlaState,
  operatorSeverityLabel,
  operatorStatusLabel,
  type OperatorCaseFilter,
} from "../_lib/operator";
import styles from "../operator.module.css";

const severityRank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

function nextActionFor(item: OperatorCaseItem): string {
  if (item.status === "unstaffed") return "接单并确认首次联系";
  if (item.status === "assigned") return "补充联系记录与处置证据";
  if (item.status === "open") return "开始处理或记录关闭原因";
  if (item.status === "resolved") return "复核后关闭或重新打开";
  return item.next_action || "查看案件证据";
}

function severityTone(value: string): "critical" | "warning" | "neutral" {
  if (value === "critical") return "critical";
  if (value === "high") return "warning";
  return "neutral";
}

function shortId(value: string | null | undefined): string {
  if (!value) return "未关联";
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

export default function OpsCarePage() {
  const router = useRouter();
  const [cases, setCases] = useState<OperatorCaseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<OperatorCaseFilter>({
    query: "",
    status: "active",
    severity: "all",
  });

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

  useEffect(() => { void load(); }, [load]);

  const now = useMemo(() => new Date(), [cases]);
  const visibleCases = useMemo(() => cases
    .filter((item) => caseMatchesFilter(item, filter, now))
    .sort((left, right) => {
      const severityDifference = (severityRank[left.severity] ?? 9) - (severityRank[right.severity] ?? 9);
      if (severityDifference !== 0) return severityDifference;
      const leftMinutes = caseSlaState(left.due_at, now).minutes ?? Number.POSITIVE_INFINITY;
      const rightMinutes = caseSlaState(right.due_at, now).minutes ?? Number.POSITIVE_INFINITY;
      return leftMinutes - rightMinutes;
    }), [cases, filter, now]);

  const unstaffed = cases.filter((item) => item.status === "unstaffed").length;
  const mine = cases.filter((item) => item.ownership_status === "owned_by_me").length;
  const overdue = cases.filter((item) => (caseSlaState(item.due_at, now).minutes ?? 0) < 0).length;
  const critical = cases.filter((item) => item.severity === "critical").length;

  return (
    <RoleShell role="operator" title="照护运营" subtitle="案件、责任、时限与证据">
      <div className={styles.workspace}>
        <header className={styles.pageHeader}>
          <div>
            <h2>安全案件队列</h2>
            <p>先接住无人负责和即将超时的案件，再进入授权证据链。队列不展示长者私人对话全文。</p>
          </div>
          <a className={styles.contextLink} href="/ops/households/readiness">查看家庭就绪</a>
        </header>

        {loading ? (
          <LoadingState label="正在同步运营案件" />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : (
          <>
            <section className={styles.summaryStrip} aria-label="运营案件状态">
              <div><span>待接单</span><strong>{unstaffed}</strong></div>
              <div><span>我的案件</span><strong>{mine}</strong></div>
              <div><span>已超时</span><strong>{overdue}</strong></div>
              <div><span>紧急</span><strong>{critical}</strong></div>
            </section>

            <section className={styles.toolbar} aria-label="案件筛选">
              <label className={styles.searchControl}>
                <span className="sr-only">搜索案件</span>
                <Search className={styles.searchIcon} size={16} aria-hidden="true" />
                <input
                  className={`${styles.searchField} ${styles.searchFieldWithIcon}`}
                  value={filter.query}
                  onChange={(event) => setFilter((value) => ({ ...value, query: event.target.value }))}
                  placeholder="搜索摘要、案件或家庭 ID"
                />
              </label>
              <div className={styles.filterGroup}>
                <label htmlFor="case-view">视图</label>
                <select
                  id="case-view"
                  className={styles.selectField}
                  value={filter.status}
                  onChange={(event) => setFilter((value) => ({ ...value, status: event.target.value as OperatorCaseFilter["status"] }))}
                >
                  <option value="active">全部进行中</option>
                  <option value="unstaffed">待接单</option>
                  <option value="mine">我的案件</option>
                  <option value="overdue">已超时</option>
                  <option value="all">当前返回全部</option>
                </select>
              </div>
              <div className={styles.filterGroup}>
                <label htmlFor="case-severity">风险</label>
                <select
                  id="case-severity"
                  className={styles.selectField}
                  value={filter.severity}
                  onChange={(event) => setFilter((value) => ({ ...value, severity: event.target.value as OperatorCaseFilter["severity"] }))}
                >
                  <option value="all">全部等级</option>
                  <option value="critical">紧急</option>
                  <option value="high">高风险</option>
                  <option value="medium">中风险</option>
                  <option value="low">低风险</option>
                </select>
              </div>
            </section>

            <section className={styles.queue} aria-label="案件列表">
              <div className={styles.queueHeader} aria-hidden="true">
                <span>案件</span><span>负责人</span><span>处理时限</span><span>下一步</span><span>操作</span>
              </div>
              {visibleCases.length === 0 ? (
                <div className={styles.emptyBlock}>
                  {cases.length === 0 ? "当前没有进行中的运营案件。" : "没有符合当前筛选条件的案件。"}
                </div>
              ) : visibleCases.map((item) => {
                const sla = caseSlaState(item.due_at, now);
                return (
                  <article key={item.id} className={styles.caseRow} data-severity={item.severity}>
                    <div className={styles.caseTitle}>
                      <div className={styles.badgeRow}>
                        <span className={styles.badge} data-tone={severityTone(item.severity)}>{operatorSeverityLabel(item.severity)}</span>
                        <span className={styles.badge}>{operatorStatusLabel(item.status)}</span>
                      </div>
                      <strong>{item.summary || "照护案件"}</strong>
                      <small>案件 {shortId(item.id)} · 家庭 {shortId(item.household_id)}</small>
                    </div>
                    <div className={styles.ownerCell}>
                      <strong><UserRoundCheck size={14} aria-hidden="true" /> {caseOwnerLabel(item)}</strong>
                      <span className={styles.cellHint}>{item.ownership_status === "owned_by_other" ? "当前账号仅可查看" : item.owner_id ? "负责人已确认" : "等待运营人员接单"}</span>
                    </div>
                    <div className={styles.slaCell}>
                      <strong data-tone={sla.tone}><Clock3 size={14} aria-hidden="true" /> {sla.label}</strong>
                      <span className={styles.cellHint}>{item.due_at ? new Date(item.due_at).toLocaleString("zh-CN") : "尚未设置处理时限"}</span>
                    </div>
                    <div className={styles.nextCell}>
                      <strong>{nextActionFor(item)}</strong>
                      <span className={styles.cellHint}>{item.trace_id ? "已有案件授权追踪" : "尚未关联追踪"}</span>
                    </div>
                    <div className={styles.rowAction}>
                      <a className={styles.compactButton} href={`/ops/care/${item.id}`}>处理 <ArrowUpRight size={15} aria-hidden="true" /></a>
                    </div>
                  </article>
                );
              })}
            </section>
          </>
        )}
      </div>
    </RoleShell>
  );
}
