"use client";

export interface CareTaskCandidate {
  id: string;
  title: string;
  status?: string;
  due_at?: string | null;
  task_type?: string;
}

interface Props {
  candidates: CareTaskCandidate[];
  verb?: string;
  disabled?: boolean;
  onSelect: (candidate: CareTaskCandidate) => void;
}

function formatDue(dueAt?: string | null): string | null {
  if (!dueAt) return null;
  try {
    const d = new Date(dueAt);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleString("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return null;
  }
}

export default function CareTaskClarifyCard({
  candidates,
  verb = "确认",
  disabled = false,
  onSelect,
}: Props) {
  if (!candidates.length) return null;

  return (
    <div className="mt-4 rounded-lg border border-status-warning bg-status-warning-soft p-4">
      <div className="mb-3 text-base font-semibold text-ink">
        请选择要{verb}的照护任务
      </div>
      <div className="grid gap-2">
        {candidates.map((c) => {
          const due = formatDue(c.due_at);
          return (
            <button
              key={c.id}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(c)}
              className="min-h-[52px] rounded-md border border-border-strong bg-surface px-4 py-3 text-left text-base text-ink transition hover:border-primary hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="font-medium">{c.title}</span>
              {due && (
                <span className="mt-1 block text-sm text-muted">{due}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
