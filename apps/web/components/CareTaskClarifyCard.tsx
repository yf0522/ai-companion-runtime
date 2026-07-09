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
    <div className="mt-2.5 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
      <div className="mb-2 text-[12px] font-medium text-amber-800">
        请选择要{verb}的照护任务
      </div>
      <div className="flex flex-wrap gap-2">
        {candidates.map((c) => {
          const due = formatDue(c.due_at);
          return (
            <button
              key={c.id}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(c)}
              className="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-left text-[13px] text-gray-800 transition hover:border-amber-400 hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="font-medium">{c.title}</span>
              {due && (
                <span className="ml-1.5 text-[11px] text-gray-500">{due}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
