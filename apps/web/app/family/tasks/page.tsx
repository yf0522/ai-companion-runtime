"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarPlus, Pencil, TimerReset, XCircle } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import * as careApi from "@/lib/api-client";
import type { CareTaskItem } from "@/lib/api-client";
import FamilyPageHeader from "../_components/FamilyPageHeader";
import FamilyTaskCard from "../_components/FamilyTaskCard";
import {
  canonicalTaskStatus,
  futureDueAt,
  isFamilyTaskActive,
  localDateInput,
  type FamilyTaskFilter,
  taskDueAt,
  taskMatchesFilter,
} from "../_lib/care-task";
import styles from "../family.module.css";

type CareTaskListOptions = {
  includeTerminal?: boolean;
  scope?: "all" | "today";
  limit?: number;
  statuses?: Array<"pending" | "due" | "done" | "snoozed" | "missed" | "cancelled">;
};
type SupportedScheduleType = NonNullable<careApi.CareTaskCreateInput["schedule_type"]>;
type CreateResult = Partial<CareTaskItem> & {
  _action?: string;
  _schedule_updated?: boolean;
  candidates?: CareTaskItem[];
  proposed?: Partial<CareTaskItem>;
};
type ExtendedCareApi = typeof careApi & {
  fetchCareTasks: (options?: CareTaskListOptions) => Promise<CareTaskItem[]>;
  snoozeCareTask?: (
    id: string,
    input: careApi.CareTaskMutationInput & { minutes: number },
  ) => Promise<Partial<CareTaskItem>>;
};

const api = careApi as ExtendedCareApi;
const weekdayOptions = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const filterLabels: Array<[FamilyTaskFilter, string]> = [
  ["attention", "需要关注"],
  ["upcoming", "接下来"],
  ["history", "历史"],
  ["all", "全部"],
];

function versionFor(task: CareTaskItem): number {
  return task.expected_version || task.version || 1;
}

function mergeTask(items: CareTaskItem[], id: string, result: Partial<CareTaskItem>): CareTaskItem[] {
  return items.map((item) => item.id === id ? { ...item, ...result, id } : item);
}

function initialOnceDate(): string {
  const value = new Date();
  value.setDate(value.getDate() + 1);
  return localDateInput(value);
}

function taskDateFields(task: CareTaskItem): { date: string; time: string } {
  const parsed = new Date(taskDueAt(task) || "");
  if (Number.isNaN(parsed.getTime())) return { date: initialOnceDate(), time: "08:00" };
  return {
    date: localDateInput(parsed),
    time: `${String(parsed.getHours()).padStart(2, "0")}:${String(parsed.getMinutes()).padStart(2, "0")}`,
  };
}

function FamilyTasksWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedFilter = searchParams.get("view") as FamilyTaskFilter | null;
  const [tasks, setTasks] = useState<CareTaskItem[]>([]);
  const [filter, setFilter] = useState<FamilyTaskFilter>(filterLabels.some(([value]) => value === requestedFilter) ? requestedFilter! : "all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [clarification, setClarification] = useState<CareTaskItem[]>([]);

  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [taskType, setTaskType] = useState("medication");
  const [timeOfDay, setTimeOfDay] = useState("08:00");
  const [scheduleType, setScheduleType] = useState<SupportedScheduleType>("daily");
  const [onceDate, setOnceDate] = useState(initialOnceDate);
  const [weekday, setWeekday] = useState((new Date().getDay() + 1) % 7);

  const [editTitle, setEditTitle] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editDate, setEditDate] = useState(initialOnceDate);
  const [editTime, setEditTime] = useState("08:00");
  const [editScheduleType, setEditScheduleType] = useState<SupportedScheduleType>("once");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Keep the default read as the primary compatibility path, then enrich it
      // with terminal history when the newer query contract is available.
      const current = await api.fetchCareTasks();
      let withHistory = current;
      try {
        withHistory = await api.fetchCareTasks({ statuses: ["done", "missed", "cancelled"], scope: "all", limit: 100 });
      } catch {
        // Current state remains usable; the history tab will honestly contain
        // only terminal rows already returned by the primary response.
      }
      const merged = new Map<string, CareTaskItem>();
      [...withHistory, ...current].forEach((task) => merged.set(task.id, task));
      setTasks(Array.from(merged.values()));
    } catch (err) {
      if (err instanceof careApi.ApiError && err.status === 401) { router.push("/login"); return; }
      setError(err instanceof careApi.ApiError && err.status === 403
        ? "当前账号没有管理长者照护任务的权限。"
        : careApi.userFacingApiError(err, "照护任务加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  const visibleTasks = useMemo(() => tasks
    .filter((task) => taskMatchesFilter(task, filter))
    .sort((left, right) => {
      const attentionRank = (task: CareTaskItem) => canonicalTaskStatus(task.status) === "missed" ? 0 : canonicalTaskStatus(task.status) === "due" ? 1 : 2;
      const rank = attentionRank(left) - attentionRank(right);
      if (rank) return rank;
      const leftTime = new Date(taskDueAt(left) || 0).getTime();
      const rightTime = new Date(taskDueAt(right) || 0).getTime();
      return filter === "history" ? rightTime - leftTime : leftTime - rightTime;
    }), [filter, tasks]);
  const activeCount = tasks.filter(isFamilyTaskActive).length;
  const attentionCount = tasks.filter((task) => taskMatchesFilter(task, "attention")).length;

  function resetCreateForm() {
    setTitle("");
    setNotes("");
    setTaskType("medication");
    setTimeOfDay("08:00");
    setScheduleType("daily");
    setOnceDate(initialOnceDate());
    setWeekday((new Date().getDay() + 1) % 7);
    setClarification([]);
  }

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    setError(null);
    setReceipt(null);
    setClarification([]);
    try {
      const dueAt = futureDueAt({ scheduleType, date: onceDate, timeOfDay, weekday, intervalDays: 1 });
      const result = await careApi.createCareTask({
        title: title.trim(),
        notes: notes.trim() || null,
        due_at: dueAt,
        schedule_type: scheduleType,
        task_type: taskType,
      }) as CreateResult;
      if (result._action === "caretask_clarify_create") {
        setClarification(result.candidates || []);
        setError("发现相似的进行中任务，因此没有重复创建。请先核对下面的候选任务。");
        return;
      }
      setReceipt(result._action === "caretask_reuse"
        ? result._schedule_updated ? "已更新同名任务的下一次时间，没有重复创建。" : "同名任务已经存在，没有重复创建。"
        : `“${title.trim()}”已建立，下一次安排为 ${new Date(dueAt).toLocaleString("zh-CN")}。`);
      resetCreateForm();
      setCreateOpen(false);
      await load();
    } catch (err) {
      setError(err instanceof Error && !(err instanceof careApi.ApiError)
        ? err.message
        : careApi.userFacingApiError(err, "创建失败，任务尚未保存。"));
    } finally {
      setCreating(false);
    }
  }

  function startEdit(task: CareTaskItem) {
    const fields = taskDateFields(task);
    setEditingId(task.id);
    setEditTitle(task.title);
    setEditNotes(task.notes || task.description || "");
    setEditDate(fields.date);
    setEditTime(fields.time);
    setEditScheduleType(
      task.schedule_type === "daily" || task.schedule_type === "weekly"
        ? task.schedule_type
        : "once",
    );
    setError(null);
    setReceipt(null);
  }

  async function handleEdit(task: CareTaskItem, event: React.FormEvent) {
    event.preventDefault();
    const dueAt = new Date(`${editDate}T${editTime}:00`);
    if (Number.isNaN(dueAt.getTime()) || dueAt <= new Date()) {
      setError("重新安排的时间需要晚于现在。");
      return;
    }
    setBusyId(task.id);
    setError(null);
    try {
      const result = await careApi.updateCareTask(task.id, {
        expected_version: versionFor(task),
        title: editTitle.trim() || task.title,
        notes: editNotes.trim() || null,
        due_at: dueAt.toISOString(),
        schedule_type: editScheduleType,
      });
      setTasks((prev) => mergeTask(prev, task.id, result));
      setEditingId(null);
      setReceipt(`“${editTitle.trim() || task.title}”的下一次时间与重复规则已更新。`);
      await load();
    } catch (err) {
      setError(careApi.userFacingApiError(err, "更新失败，原安排仍然保留。"));
    } finally {
      setBusyId(null);
    }
  }

  async function handleSnooze(task: CareTaskItem) {
    if (!api.snoozeCareTask) {
      setError("当前服务尚未开放延后动作，原任务没有改变。请使用“重新安排”设置新的时间。");
      return;
    }
    setBusyId(task.id);
    setError(null);
    try {
      const result = await api.snoozeCareTask(task.id, {
        ...careApi.mutationInputForTask(task, "family-task-snooze"),
        minutes: 30,
      });
      setTasks((prev) => mergeTask(prev, task.id, result));
      setReceipt(`“${task.title}”已延后 30 分钟。`);
      await load();
    } catch (err) {
      setError(careApi.userFacingApiError(err, "延后失败，原时间仍然有效。"));
    } finally {
      setBusyId(null);
    }
  }

  async function handleCancel(task: CareTaskItem) {
    if (!window.confirm(`确定停用“${task.title}”吗？历史记录会保留。`)) return;
    setBusyId(task.id);
    setError(null);
    try {
      const result = await careApi.cancelCareTask(task.id, careApi.mutationInputForTask(task, "family-task-cancel"));
      setTasks((prev) => mergeTask(prev, task.id, { status: "cancelled", is_active: false, ...result }));
      setReceipt(`“${task.title}”已停用，历史记录仍可查看。`);
      setFilter("history");
      await load();
    } catch (err) {
      setError(careApi.userFacingApiError(err, "停用失败，任务仍按原计划保留。"));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <RoleShell role="family" title="照护任务">
      <div className={styles.workspace}>
        <FamilyPageHeader
          context="照护安排"
          title={attentionCount > 0 ? `有 ${attentionCount} 项任务需要确认` : "接下来的照护安排"}
          description="按真实状态查看到期、错过和历史记录；停用不会抹掉已经发生的结果。"
          action={<button type="button" className="btn-primary" onClick={() => setCreateOpen((value) => !value)}><CalendarPlus size={17} /> {createOpen ? "收起新增" : "新增照护任务"}</button>}
        />

        {createOpen && (
          <section className={styles.surface} aria-label="新增照护任务">
            <div className={styles.sectionHeading}>
              <div><h3>新增任务</h3><p>下一次触发时间必须晚于现在；重复任务会从这个时间开始。</p></div>
            </div>
            <form className={styles.form} onSubmit={handleCreate} style={{ marginTop: 18 }}>
              <div className={styles.formRow}>
                <label className={styles.field}>任务名称
                  <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：晚饭后按医嘱服药" required />
                </label>
                <label className={styles.field}>任务类型
                  <select value={taskType} onChange={(event) => setTaskType(event.target.value)}>
                    <option value="medication">服药</option><option value="appointment">复诊或预约</option><option value="hydration">饮水</option><option value="exercise">运动</option><option value="other">其他</option>
                  </select>
                </label>
              </div>
              <label className={styles.field}>照护说明
                <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="只写已经确认的安排，例如“按医嘱服用”；不要在这里新建剂量建议。" />
              </label>
              <div className={styles.formRow}>
                <label className={styles.field}>重复
                  <select value={scheduleType} onChange={(event) => setScheduleType(event.target.value as SupportedScheduleType)}>
                    <option value="once">一次</option><option value="daily">每天</option><option value="weekly">每周</option>
                  </select>
                </label>
                <label className={styles.field}>时间
                  <input type="time" value={timeOfDay} onChange={(event) => setTimeOfDay(event.target.value)} required />
                </label>
              </div>
              {scheduleType === "once" && <label className={styles.field}>日期<input type="date" min={localDateInput(new Date())} value={onceDate} onChange={(event) => setOnceDate(event.target.value)} required /></label>}
              {scheduleType === "weekly" && <label className={styles.field}>星期<select value={weekday} onChange={(event) => setWeekday(Number(event.target.value))}>{weekdayOptions.map((label, index) => <option key={label} value={index}>{label}</option>)}</select></label>}
              <div className={styles.formActions}>
                <button type="submit" className="btn-primary" disabled={creating || !title.trim()}>{creating ? "正在保存" : "保存照护任务"}</button>
                <button type="button" className="btn-secondary" onClick={() => { resetCreateForm(); setCreateOpen(false); }}>取消</button>
              </div>
            </form>
          </section>
        )}

        {receipt && <div className={styles.notice} role="status"><strong>安排已更新</strong>{receipt}</div>}
        {error && tasks.length > 0 && <div className={styles.notice} data-tone="critical" role="alert"><strong>这次操作没有完成</strong>{error}</div>}
        {clarification.length > 0 && (
          <section className={styles.surfaceSoft} aria-label="相似任务">
            <h3>先核对已有任务</h3>
            <div className={styles.stack} style={{ marginTop: 14 }}>{clarification.map((task) => <FamilyTaskCard key={task.id} task={task} />)}</div>
          </section>
        )}

        <div className={styles.filterBar} role="group" aria-label="筛选照护任务">
          {filterLabels.map(([value, label]) => <button key={value} type="button" data-active={filter === value ? "true" : "false"} onClick={() => setFilter(value)}>{label}{value === "attention" ? ` ${attentionCount}` : ""}</button>)}
        </div>

        {loading ? (
          <LoadingState label="正在加载照护任务" />
        ) : error && tasks.length === 0 ? (
          <ErrorState description={error} onRetry={load} />
        ) : visibleTasks.length === 0 ? (
          <EmptyState title={filter === "attention" ? "目前没有需要确认的任务" : "这个筛选下还没有任务"} description={filter === "history" ? "完成、错过或停用的任务会保留在这里。" : "可以切换筛选或新增照护任务。"} />
        ) : (
          <section className={styles.stack} aria-label="照护任务清单">
            {visibleTasks.map((task) => {
              const status = canonicalTaskStatus(task.status);
              const mutable = ["pending", "due", "snoozed"].includes(status);
              const canReplan = mutable && task.schedule_type !== "interval";
              return (
                <FamilyTaskCard
                  key={task.id}
                  task={task}
                  actions={mutable && <>
                    {canReplan && <button type="button" className="btn-secondary" disabled={busyId === task.id} onClick={() => startEdit(task)}><Pencil size={16} /> 重新安排</button>}
                    <button type="button" className="btn-secondary" disabled={busyId === task.id} onClick={() => handleSnooze(task)}><TimerReset size={16} /> 延后 30 分钟</button>
                    <button type="button" className="btn-secondary" disabled={busyId === task.id} onClick={() => handleCancel(task)}><XCircle size={16} /> 停用</button>
                  </>}
                >
                  {editingId === task.id && (
                    <form className={styles.inlineForm} onSubmit={(event) => handleEdit(task, event)}>
                      <div className={styles.formRow}>
                        <label className={styles.field}>任务名称<input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} /></label>
                        <label className={styles.field}>日期<input type="date" min={localDateInput(new Date())} value={editDate} onChange={(event) => setEditDate(event.target.value)} /></label>
                      </div>
                      <div className={styles.formRow}>
                        <label className={styles.field}>时间<input type="time" value={editTime} onChange={(event) => setEditTime(event.target.value)} /></label>
                        <label className={styles.field}>重复<select value={editScheduleType} onChange={(event) => setEditScheduleType(event.target.value as SupportedScheduleType)}><option value="once">一次</option><option value="daily">每天</option><option value="weekly">每周</option></select></label>
                      </div>
                      <label className={styles.field}>说明<input value={editNotes} onChange={(event) => setEditNotes(event.target.value)} /></label>
                      <div className={styles.formActions}><button type="submit" className="btn-primary" disabled={busyId === task.id}>保存重新安排</button><button type="button" className="btn-secondary" onClick={() => setEditingId(null)}>取消</button></div>
                    </form>
                  )}
                </FamilyTaskCard>
              );
            })}
          </section>
        )}

        {!loading && !error && (
          <section className="metric-strip" aria-label="照护任务统计">
            <div><p className="eyebrow">全部</p><p className="text-2xl font-semibold text-ink">{tasks.length}</p></div>
            <div><p className="eyebrow">进行中</p><p className="text-2xl font-semibold text-ink">{activeCount}</p></div>
          </section>
        )}
      </div>
    </RoleShell>
  );
}

export default function FamilyTasksPage() {
  return (
    <Suspense fallback={(
      <RoleShell role="family" title="照护任务">
        <LoadingState label="正在加载照护任务" />
      </RoleShell>
    )}>
      <FamilyTasksWorkspace />
    </Suspense>
  );
}
