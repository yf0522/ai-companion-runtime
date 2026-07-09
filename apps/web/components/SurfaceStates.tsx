type SurfaceTone = "info" | "success" | "warning" | "critical" | "offline";

const toneClass: Record<SurfaceTone, string> = {
  info: "border-status-info bg-status-info-soft text-ink",
  success: "border-status-success bg-status-success-soft text-ink",
  warning: "border-status-warning bg-status-warning-soft text-ink",
  critical: "border-status-critical bg-status-critical-soft text-ink",
  offline: "border-status-offline bg-status-offline-soft text-ink",
};

export function LoadingState({ label = "正在加载" }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-md border border-border bg-surface p-4 text-base text-muted"
    >
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-border bg-surface p-5">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <p className="mt-1 text-base leading-7 text-muted">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "加载失败",
  description,
  onRetry,
}: {
  title?: string;
  description: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-md border border-status-critical bg-status-critical-soft p-5 text-ink"
    >
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mt-1 text-base leading-7">{description}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-secondary mt-4">
          重试
        </button>
      )}
    </div>
  );
}

export function StatusBanner({
  tone = "info",
  title,
  children,
}: {
  tone?: SurfaceTone;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={`rounded-md border p-4 ${toneClass[tone]}`}>
      <div className="text-base font-semibold">{title}</div>
      {children && <div className="mt-1 text-sm leading-6">{children}</div>}
    </div>
  );
}
