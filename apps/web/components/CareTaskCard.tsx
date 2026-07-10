import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { CalendarClock, Check, Repeat2, UserRound } from "lucide-react";
import type { CareTaskItem } from "@/lib/api-client";

function formatDateTime(value: string | null | undefined): string { if (!value) return "尚未安排"; const date = new Date(value); return Number.isNaN(date.getTime()) ? "时间待确认" : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
function scheduleLabel(value: string | null | undefined): string { return ({ daily: "每天", weekly: "每周", once: "一次", interval: "间隔" } as Record<string, string>)[value || ""] || "计划待确认"; }
function taskIsActive(task: CareTaskItem): boolean { return typeof task.is_active === "boolean" ? task.is_active : !["completed", "cancelled", "archived", "expired"].includes(task.status || ""); }
function statusLabel(task: CareTaskItem): string { return ({ pending: "待处理", scheduled: "已安排", active: "进行中", completed: "已完成", snoozed: "已延后", cancelled: "已取消", archived: "已归档", expired: "已过期" } as Record<string, string>)[task.status || ""] || (taskIsActive(task) ? "进行中" : "已停用"); }

export default function CareTaskCard({ task, actionLabel, actionBusy, onAction, secondaryAction }: { task: CareTaskItem; actionLabel?: string; actionBusy?: boolean; onAction?: () => void; secondaryAction?: React.ReactNode; }) {
  const active = taskIsActive(task);
  const description = task.notes || task.description;
  const dueAt = task.next_fire_at || task.due_at;
  return (
    <article className="care-card">
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 20, alignItems: "start" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 9 }}>
            <h3 style={{ margin: 0, fontSize: 20, lineHeight: 1.35 }}>{task.title}</h3>
            <Badge label={statusLabel(task)} variant={active ? "info" : "neutral"} />
          </div>
          {description && <Text display="block" color="secondary" style={{ marginTop: 7, lineHeight: 1.65 }}>{description}</Text>}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 18, marginTop: 18 }}>
            <Text type="supporting" color="secondary"><Icon icon={CalendarClock} size="xsm" /> 下次 {formatDateTime(dueAt)}</Text>
            <Text type="supporting" color="secondary"><Icon icon={Repeat2} size="xsm" /> {scheduleLabel(task.schedule_type)}</Text>
            <Text type="supporting" color="secondary"><Icon icon={UserRound} size="xsm" /> {task.created_by === "family" ? "家属创建" : "本人创建"}</Text>
          </div>
        </div>
        {(onAction || secondaryAction) && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" }}>
            {onAction && actionLabel && <Button label={actionBusy ? "处理中" : actionLabel} variant="primary" isLoading={actionBusy} onClick={onAction} icon={<Icon icon={Check} size="sm" />} />}
            {secondaryAction}
          </div>
        )}
      </div>
    </article>
  );
}
