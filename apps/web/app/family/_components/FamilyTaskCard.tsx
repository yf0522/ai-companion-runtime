import type { ReactNode } from "react";
import { CalendarClock, History, Repeat2, UserRound } from "lucide-react";
import type { CareTaskItem } from "@/lib/api-client";
import {
  canonicalTaskStatus,
  formatCareTime,
  isFamilyTaskActive,
  scheduleLabel,
  taskDueAt,
  taskStatusLabel,
} from "../_lib/care-task";
import styles from "../family.module.css";

export default function FamilyTaskCard({
  task,
  actions,
  compactHref,
  children,
}: {
  task: CareTaskItem;
  actions?: ReactNode;
  compactHref?: string;
  children?: ReactNode;
}) {
  const status = canonicalTaskStatus(task.status);
  const description = task.notes || task.description;
  const actor = task.created_by === "family" ? "家属创建" : task.created_by ? "本人创建" : "创建人未记录";
  const tone = status === "missed" ? "critical" : status === "due" ? "warning" : status === "done" ? "success" : "neutral";

  return (
    <article className={styles.taskCard} data-tone={tone} data-active={isFamilyTaskActive(task) ? "true" : "false"}>
      <div className={styles.cardHeading}>
        <div>
          <h3>{task.title}</h3>
          {description && <p>{description}</p>}
        </div>
        <span className={styles.statePill} data-tone={tone}>{taskStatusLabel(task)}</span>
      </div>
      <dl className={styles.factGrid}>
        <div>
          <dt><CalendarClock size={16} />{status === "done" ? "完成时间" : "下次时间"}</dt>
          <dd>{formatCareTime(taskDueAt(task))}</dd>
        </div>
        <div>
          <dt><Repeat2 size={16} />重复</dt>
          <dd>{scheduleLabel(task.schedule_type)}</dd>
        </div>
        <div>
          <dt><UserRound size={16} />责任来源</dt>
          <dd>{actor}</dd>
        </div>
        <div>
          <dt><History size={16} />最近状态</dt>
          <dd>{taskStatusLabel(task)} · 版本 {task.version || task.expected_version || "未记录"}</dd>
        </div>
      </dl>
      {(actions || compactHref) && (
        <div className={styles.cardActions}>
          {compactHref && <a className="btn-secondary" href={compactHref} aria-label={`查看${task.title}`}>查看任务</a>}
          {actions}
        </div>
      )}
      {children}
    </article>
  );
}
