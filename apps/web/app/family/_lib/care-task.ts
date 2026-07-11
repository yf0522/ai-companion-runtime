import type { CareTaskItem } from "@/lib/api-client";

export type FamilyTaskFilter = "attention" | "upcoming" | "history" | "all";
export type CanonicalCareTaskStatus =
  | "pending"
  | "due"
  | "done"
  | "snoozed"
  | "missed"
  | "cancelled"
  | "unknown";

const terminalStatuses = new Set<CanonicalCareTaskStatus>(["done", "missed", "cancelled"]);

export function canonicalTaskStatus(status: string | null | undefined): CanonicalCareTaskStatus {
  const value = (status || "").toLowerCase();
  if (value === "completed" || value === "acknowledged") return "done";
  if (value === "expired") return "missed";
  if (value === "archived") return "cancelled";
  if (value === "scheduled" || value === "active") return "pending";
  if (["pending", "due", "done", "snoozed", "missed", "cancelled"].includes(value)) {
    return value as CanonicalCareTaskStatus;
  }
  return "unknown";
}

export function taskStatusLabel(task: Pick<CareTaskItem, "status" | "is_active">): string {
  if (task.is_active === false && !terminalStatuses.has(canonicalTaskStatus(task.status))) return "已停用";
  return {
    pending: "待处理",
    due: "现在到期",
    done: "已完成",
    snoozed: "已延后",
    missed: "已错过",
    cancelled: "已取消",
    unknown: "状态待确认",
  }[canonicalTaskStatus(task.status)];
}

export function isFamilyTaskActive(task: Pick<CareTaskItem, "status" | "is_active">): boolean {
  if (task.is_active === false) return false;
  return !terminalStatuses.has(canonicalTaskStatus(task.status));
}

export function taskMatchesFilter(task: CareTaskItem, filter: FamilyTaskFilter): boolean {
  const status = canonicalTaskStatus(task.status);
  if (filter === "attention") return status === "due" || status === "missed";
  if (filter === "upcoming") return isFamilyTaskActive(task) && status !== "due";
  if (filter === "history") return terminalStatuses.has(status);
  return true;
}

export function taskDueAt(task: CareTaskItem): string | null {
  return task.next_fire_at || task.due_at || null;
}

export function formatCareTime(value: string | null | undefined, fallback = "尚未安排"): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function scheduleLabel(value: string | null | undefined): string {
  return {
    once: "一次",
    daily: "每天",
    weekly: "每周",
    interval: "按间隔",
  }[value || ""] || "重复规则未记录";
}

function clockParts(timeOfDay: string): [number, number] {
  const [hours, minutes] = timeOfDay.split(":").map(Number);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return [8, 0];
  return [Math.min(23, Math.max(0, hours)), Math.min(59, Math.max(0, minutes))];
}

export function localDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function futureDueAt({
  scheduleType,
  date,
  timeOfDay,
  weekday,
  intervalDays,
  now = new Date(),
}: {
  scheduleType: string;
  date: string;
  timeOfDay: string;
  weekday: number;
  intervalDays: number;
  now?: Date;
}): string {
  const [hours, minutes] = clockParts(timeOfDay);
  let due = new Date(now);
  due.setSeconds(0, 0);

  if (scheduleType === "once") {
    const parsed = new Date(`${date}T${timeOfDay}:00`);
    if (Number.isNaN(parsed.getTime()) || parsed <= now) {
      throw new Error("一次性任务的时间需要晚于现在。");
    }
    return parsed.toISOString();
  }

  if (scheduleType === "interval") {
    due.setDate(due.getDate() + Math.max(1, intervalDays));
    due.setHours(hours, minutes, 0, 0);
    return due.toISOString();
  }

  if (scheduleType === "weekly") {
    const target = Math.min(6, Math.max(0, weekday));
    const delta = (target - due.getDay() + 7) % 7;
    due.setDate(due.getDate() + delta);
    due.setHours(hours, minutes, 0, 0);
    if (due <= now) due.setDate(due.getDate() + 7);
    return due.toISOString();
  }

  due.setHours(hours, minutes, 0, 0);
  if (due <= now) due.setDate(due.getDate() + 1);
  return due.toISOString();
}

