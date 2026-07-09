import type { ReminderItem } from "@/lib/api-client";

function formatDateTime(value: string | null): string {
  if (!value) return "尚未安排";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scheduleLabel(value: string): string {
  return (
    {
      daily: "每天",
      weekly: "每周",
      once: "一次",
      interval: "间隔",
    }[value] || "计划待确认"
  );
}

export default function CareTaskCard({
  task,
  actionLabel,
  actionBusy,
  onAction,
  secondaryAction,
}: {
  task: ReminderItem;
  actionLabel?: string;
  actionBusy?: boolean;
  onAction?: () => void;
  secondaryAction?: React.ReactNode;
}) {
  const statusText = task.is_active ? "进行中" : "已停用";
  const statusClass = task.is_active
    ? "border-status-info bg-status-info-soft text-ink"
    : "border-status-unknown bg-status-unknown-soft text-muted";

  return (
    <article className="rounded-md border border-border bg-surface p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold leading-7 text-ink">
              {task.title}
            </h3>
            <span className={`rounded-full border px-3 py-1 text-sm ${statusClass}`}>
              {statusText}
            </span>
          </div>
          {task.description && (
            <p className="mt-1 text-base leading-7 text-muted">
              {task.description}
            </p>
          )}
          <dl className="mt-3 grid gap-2 text-sm text-muted sm:grid-cols-3">
            <div>
              <dt className="font-medium text-ink">下次提醒</dt>
              <dd>{formatDateTime(task.next_fire_at)}</dd>
            </div>
            <div>
              <dt className="font-medium text-ink">重复</dt>
              <dd>{scheduleLabel(task.schedule_type)}</dd>
            </div>
            <div>
              <dt className="font-medium text-ink">来源</dt>
              <dd>{task.created_by === "family" ? "家属创建" : "本人创建"}</dd>
            </div>
          </dl>
        </div>
        {(onAction || secondaryAction) && (
          <div className="flex flex-wrap gap-2 sm:justify-end">
            {onAction && actionLabel && (
              <button
                type="button"
                disabled={actionBusy}
                onClick={onAction}
                className="btn-primary"
              >
                {actionBusy ? "处理中" : actionLabel}
              </button>
            )}
            {secondaryAction}
          </div>
        )}
      </div>
    </article>
  );
}
