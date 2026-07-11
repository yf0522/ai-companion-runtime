import type { CareTaskItem } from "@/lib/api-client";

export type CanonicalCareTaskStatus =
  | "pending"
  | "due"
  | "done"
  | "snoozed"
  | "missed"
  | "cancelled"
  | "unknown";

const statusAliases: Record<string, CanonicalCareTaskStatus> = {
  scheduled: "pending",
  active: "due",
  completed: "done",
  acknowledged: "done",
  archived: "cancelled",
  expired: "missed",
  failed: "missed",
};

const terminalStatuses = new Set<CanonicalCareTaskStatus>([
  "done",
  "missed",
  "cancelled",
]);

export function normalizeCareTaskStatus(
  status: string | null | undefined,
): CanonicalCareTaskStatus {
  const normalized = (status || "").trim().toLowerCase();
  if (normalized in statusAliases) return statusAliases[normalized];
  if (["pending", "due", "done", "snoozed", "missed", "cancelled"].includes(normalized)) {
    return normalized as CanonicalCareTaskStatus;
  }
  return "unknown";
}

export function careTaskStatusLabel(status: string | null | undefined): string {
  return {
    pending: "已安排",
    due: "现在需要处理",
    done: "已完成",
    snoozed: "已延后",
    missed: "已错过",
    cancelled: "已取消",
    unknown: "状态待确认",
  }[normalizeCareTaskStatus(status)];
}

export function isTerminalCareTaskStatus(status: string | null | undefined): boolean {
  return terminalStatuses.has(normalizeCareTaskStatus(status));
}

export function isCareTaskActive(task: Pick<CareTaskItem, "is_active" | "status">): boolean {
  if (isTerminalCareTaskStatus(task.status)) return false;
  return typeof task.is_active === "boolean" ? task.is_active : true;
}

export function isCareTaskActionable(
  task: Pick<CareTaskItem, "is_active" | "status">,
): boolean {
  const status = normalizeCareTaskStatus(task.status);
  if (status === "missed") return true;
  return ["pending", "due", "snoozed"].includes(status) && task.is_active !== false;
}
