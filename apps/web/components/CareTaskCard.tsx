import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { Text } from "@astryxdesign/core/Text";
import { CalendarClock, Check, ChevronRight, Repeat2, UserRound } from "lucide-react";
import type { CareTaskItem } from "@/lib/api-client";
import { careTaskStatusLabel, isCareTaskActive, normalizeCareTaskStatus } from "@/lib/care-task-state";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "尚未安排";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "时间待确认"
    : date.toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function scheduleLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    daily: "每天",
    weekly: "每周",
    once: "一次",
    interval: "间隔",
  };
  return labels[value || ""] || "计划待确认";
}
function statusLabel(task: CareTaskItem): string {
  if (task.is_active === false && normalizeCareTaskStatus(task.status) === "unknown") return "已停用";
  return careTaskStatusLabel(task.status);
}

export default function CareTaskCard({
  task,
  actionLabel,
  actionBusy,
  onAction,
  secondaryAction,
  compact = false,
  compactHref,
}: {
  task: CareTaskItem;
  actionLabel?: string;
  actionBusy?: boolean;
  onAction?: () => void;
  secondaryAction?: React.ReactNode;
  compact?: boolean;
  compactHref?: string;
}) {
  const active = isCareTaskActive(task);
  const description = task.notes || task.description;
  const dueAt = task.snooze_until || task.next_fire_at || task.due_at;
  return (
    <article className="care-card care-task-card" data-compact={compact ? "true" : "false"}>
      <div className="care-task-layout">
        {compact && <div className="care-task-icon" aria-hidden="true"><Icon icon={CalendarClock} size="sm" /></div>}
        <div className="care-task-copy">
          <div className="care-task-heading">
            <h3>{task.title}</h3>
            <Badge label={statusLabel(task)} variant={active ? "info" : "neutral"} />
          </div>
          {description && <Text display="block" color="secondary" className="care-task-description">{description}</Text>}
          <div className="care-task-meta">
            <Text type="supporting" color="secondary"><Icon icon={CalendarClock} size="xsm" /> 下次 {formatDateTime(dueAt)}</Text>
            <Text type="supporting" color="secondary"><Icon icon={Repeat2} size="xsm" /> {scheduleLabel(task.schedule_type)}</Text>
            <Text type="supporting" color="secondary"><Icon icon={UserRound} size="xsm" /> {task.created_by === "family" ? "家属创建" : "本人创建"}</Text>
          </div>
        </div>
        {(onAction || secondaryAction) && (
          <div className="care-task-actions">
            {onAction && actionLabel && <Button label={actionBusy ? "处理中" : actionLabel} variant="primary" isLoading={actionBusy} onClick={onAction} icon={<Icon icon={Check} size="sm" />} />}
            {secondaryAction}
          </div>
        )}
        {compact && compactHref && <a className="care-task-chevron" href={compactHref} aria-label={`查看${task.title}`}><ChevronRight size={19} /></a>}
      </div>
    </article>
  );
}
