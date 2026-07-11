export type OperatorCaseLike = {
  id: string;
  summary?: string | null;
  status?: string | null;
  severity?: string | null;
  ownership_status?: string | null;
  owner_id?: string | null;
  household_id?: string | null;
  due_at?: string | null;
  allowed_transitions?: string[];
};

export type OperatorCaseFilter = {
  query: string;
  status: "active" | "unstaffed" | "mine" | "overdue" | "all";
  severity: "all" | "critical" | "high" | "medium" | "low";
};

const statusLabels: Record<string, string> = {
  unstaffed: "待接单",
  open: "待处理",
  assigned: "处理中",
  resolved: "已解决",
  closed: "已关闭",
};

const severityLabels: Record<string, string> = {
  critical: "紧急",
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

export function operatorStatusLabel(status: string | null | undefined): string {
  return statusLabels[(status || "").toLowerCase()] || "状态待确认";
}

export function operatorSeverityLabel(severity: string | null | undefined): string {
  return severityLabels[(severity || "").toLowerCase()] || "风险待确认";
}

export function caseOwnerLabel(item: OperatorCaseLike): string {
  if (item.ownership_status === "owned_by_me") return "我的案件";
  if (item.ownership_status === "owned_by_other" || item.owner_id) return "其他运营人员负责";
  return "尚未接单";
}

export function caseSlaState(
  dueAt: string | null | undefined,
  now = new Date(),
): { tone: "critical" | "warning" | "neutral"; label: string; minutes: number | null } {
  if (!dueAt) return { tone: "neutral", label: "未设置时限", minutes: null };
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return { tone: "neutral", label: "时限待确认", minutes: null };
  const minutes = Math.round((due.getTime() - now.getTime()) / 60_000);
  if (minutes < 0) return { tone: "critical", label: `已超时 ${Math.abs(minutes)} 分钟`, minutes };
  if (minutes <= 60) return { tone: "warning", label: `${minutes} 分钟内到期`, minutes };
  if (minutes < 24 * 60) return { tone: "neutral", label: `${Math.ceil(minutes / 60)} 小时内到期`, minutes };
  return { tone: "neutral", label: due.toLocaleString("zh-CN"), minutes };
}

export function allowedCaseTransitions(item: OperatorCaseLike): string[] {
  if (item.ownership_status === "owned_by_other") return [];
  return Array.isArray(item.allowed_transitions) ? item.allowed_transitions : [];
}

export function transitionLabel(from: string | null | undefined, to: string): string {
  if (to === "assigned" && from === "unstaffed") return "接单";
  if (to === "assigned") return "开始处理";
  if (to === "resolved") return "标记已解决";
  if (to === "closed") return "关闭案件";
  if (to === "open") return "重新打开";
  return operatorStatusLabel(to);
}

export function caseMatchesFilter(
  item: OperatorCaseLike,
  filter: OperatorCaseFilter,
  now = new Date(),
): boolean {
  if (filter.severity !== "all" && item.severity !== filter.severity) return false;
  if (filter.status === "unstaffed" && item.status !== "unstaffed") return false;
  if (filter.status === "mine" && item.ownership_status !== "owned_by_me") return false;
  if (filter.status === "overdue" && (caseSlaState(item.due_at, now).minutes ?? 0) >= 0) return false;
  if (filter.status === "active" && ["resolved", "closed"].includes(item.status || "")) return false;
  const query = filter.query.trim().toLowerCase();
  if (!query) return true;
  return [item.summary, item.id, item.household_id]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(query));
}

export function traceStatusLabel(status: string | null | undefined): string {
  const value = (status || "").toLowerCase();
  if (value === "completed" || value === "success") return "已完成";
  if (value === "failed" || value === "error") return "失败";
  if (value === "timeout") return "超时";
  return "状态未记录";
}

export function isFailedTraceStatus(status: string | null | undefined): boolean {
  return ["failed", "error", "timeout"].includes((status || "").toLowerCase());
}

export function formatRecordedMetric(
  value: number | null | undefined,
  suffix = "",
): string {
  return value === null || value === undefined ? "未记录" : `${value}${suffix}`;
}
