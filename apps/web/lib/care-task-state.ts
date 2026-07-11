import type { CareTaskItem } from "@/lib/api-client";

const inactiveStatuses = new Set(["completed", "cancelled", "archived", "expired"]);

export function isTerminalCareTaskStatus(status: string | null | undefined): boolean {
  return inactiveStatuses.has(status || "");
}

export function isCareTaskActive(task: Pick<CareTaskItem, "is_active" | "status">): boolean {
  if (isTerminalCareTaskStatus(task.status)) return false;
  return typeof task.is_active === "boolean" ? task.is_active : true;
}
