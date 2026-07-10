"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import CareTaskCard from "@/components/CareTaskCard";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  cancelCareTask,
  createCareTask,
  fetchCareTasks,
  mutationInputForTask,
  type CareTaskItem,
  userFacingApiError,
} from "@/lib/api-client";

function dueAtForToday(timeOfDay: string): string {
  const [hours = "8", minutes = "0"] = timeOfDay.split(":");
  const dueAt = new Date();
  dueAt.setHours(Number(hours), Number(minutes), 0, 0);
  return dueAt.toISOString();
}

export default function FamilyTasksPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<CareTaskItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [timeOfDay, setTimeOfDay] = useState("08:00");
  const [scheduleType, setScheduleType] = useState("daily");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTasks(await fetchCareTasks());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(
        err instanceof ApiError && err.status === 403
          ? "当前账号没有管理长者照护任务的权限。"
          : userFacingApiError(err, "照护任务加载失败，请稍后重试。"),
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await createCareTask({
        title: title.trim(),
        notes: description.trim() || null,
        due_at: dueAtForToday(timeOfDay),
        schedule_type: scheduleType,
        task_type: "medication",
      });
      setTitle("");
      setDescription("");
      setTimeOfDay("08:00");
      setScheduleType("daily");
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "创建失败，任务尚未保存。"));
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(task: CareTaskItem) {
    setDeletingId(task.id);
    setError(null);
    try {
      await cancelCareTask(task.id, mutationInputForTask(task, "care-task-cancel"));
      setTasks((prev) => prev.filter((item) => item.id !== task.id));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(userFacingApiError(err, "删除失败，任务仍保留。"));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <RoleShell
      role="family"
      title="照护任务"
      subtitle="这里管理照护意图、版本和投递计划；每次变更都会带上幂等键和预期版本。"
    >
      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <form
          onSubmit={handleCreate}
          className="rounded-md border border-border bg-surface p-5"
        >
          <h2 className="text-xl font-semibold text-ink">新增任务</h2>
          <div className="mt-4 grid gap-4">
            <label className="grid gap-1 text-base font-medium text-ink">
              任务名称
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="min-h-11 rounded-md border border-border bg-surface px-3 text-base"
                placeholder="例如：晚饭后吃药"
              />
            </label>
            <label className="grid gap-1 text-base font-medium text-ink">
              说明
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="min-h-24 rounded-md border border-border bg-surface px-3 py-2 text-base"
                placeholder="剂量、注意事项或需要家人确认的内容"
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1 text-base font-medium text-ink">
                时间
                <input
                  type="time"
                  value={timeOfDay}
                  onChange={(event) => setTimeOfDay(event.target.value)}
                  className="min-h-11 rounded-md border border-border bg-surface px-3 text-base"
                />
              </label>
              <label className="grid gap-1 text-base font-medium text-ink">
                重复
                <select
                  value={scheduleType}
                  onChange={(event) => setScheduleType(event.target.value)}
                  className="min-h-11 rounded-md border border-border bg-surface px-3 text-base"
                >
                  <option value="daily">每天</option>
                  <option value="weekly">每周</option>
                  <option value="once">一次</option>
                  <option value="interval">间隔</option>
                </select>
              </label>
            </div>
            <button
              type="submit"
              disabled={creating || !title.trim()}
              className="btn-primary"
            >
              {creating ? "正在保存" : "保存照护任务"}
            </button>
          </div>
        </form>

        <section className="grid gap-3">
          {error && <ErrorState description={error} onRetry={load} />}
          {loading ? (
            <LoadingState label="正在加载照护任务" />
          ) : tasks.length === 0 && !error ? (
            <EmptyState title="还没有照护任务" description="新增一个任务后，长者和家属都能看到对应状态。" />
          ) : (
            tasks.map((task) => (
              <CareTaskCard
                key={task.id}
                task={task}
                secondaryAction={
                  <button
                    type="button"
                    disabled={deletingId === task.id}
                    onClick={() => handleDelete(task)}
                    className="btn-secondary border-status-critical text-ink"
                  >
                    {deletingId === task.id ? "删除中" : "删除"}
                  </button>
                }
              />
            ))
          )}
        </section>
      </div>
    </RoleShell>
  );
}
