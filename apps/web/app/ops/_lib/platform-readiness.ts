import type {
  OperatorPlatformReadinessCheck,
  OperatorPlatformReadinessResponse,
  PlatformReadinessStatus,
} from "@/lib/api-client";

export const PLATFORM_READINESS_STATUSES = [
  "ready",
  "degraded",
  "unsafe_to_serve",
] as const;

export type {
  OperatorPlatformReadinessCheck,
  OperatorPlatformReadinessResponse,
  PlatformReadinessStatus,
};
export type PlatformEvidenceState = "fresh" | "stale" | "unknown";
export type PlatformPresentationState = PlatformReadinessStatus | "stale" | "unknown";
export type PlatformReadinessTone = "success" | "warning" | "critical" | "unknown";

export interface PlatformReadinessCheckView {
  id: string;
  label: string;
  status: PlatformReadinessStatus | "unknown";
  statusLabel: string;
  tone: PlatformReadinessTone;
  summary: string;
  durationMs: number | null;
  owner: string;
  nextAction: string;
  runbook: string;
  observed: Array<{ label: string; value: string }>;
}

export interface PlatformReadinessView {
  state: PlatformPresentationState;
  sourceStatus: PlatformReadinessStatus | null;
  evidenceState: PlatformEvidenceState;
  tone: PlatformReadinessTone;
  title: string;
  description: string;
  statusLabel: string;
  checkedAt: string | null;
  ageSeconds: number | null;
  durationMs: number | null;
  checkCount: number | null;
  checks: PlatformReadinessCheckView[];
}

const STATUS_RANK: Record<PlatformReadinessStatus, number> = {
  ready: 0,
  degraded: 1,
  unsafe_to_serve: 2,
};

const CHECK_COPY: Record<PlatformReadinessStatus | "unknown", {
  label: string;
  tone: PlatformReadinessTone;
}> = {
  ready: { label: "已就绪", tone: "success" },
  degraded: { label: "能力受限", tone: "warning" },
  unsafe_to_serve: { label: "阻止服务", tone: "critical" },
  unknown: { label: "状态待确认", tone: "unknown" },
};

const READINESS_COPY: Record<
  PlatformReadinessStatus,
  Pick<PlatformReadinessView, "tone" | "title" | "description" | "statusLabel">
> = {
  ready: {
    tone: "success",
    title: "平台可以承载服务",
    description: "关键运行依赖已通过本次检查。继续关注证据时间，并在变更后重新确认。",
    statusLabel: "可承载服务",
  },
  degraded: {
    tone: "warning",
    title: "平台可用，但能力受限",
    description: "核心服务仍可运行，但部分能力不可用。请按受限检查项完成修复。",
    statusLabel: "能力受限",
  },
  unsafe_to_serve: {
    tone: "critical",
    title: "平台不可承载服务",
    description: "至少一项关键检查阻止服务。请停止放量，并按负责人和下一步完成修复。",
    statusLabel: "不可承载服务",
  },
};

const OBSERVED_LABELS: Record<string, string> = {
  configured: "已配置",
  enabled: "已启用",
  mode: "运行模式",
  provider: "提供方",
  queue_depth: "队列深度",
  pending_count: "待处理",
  applied_revision: "当前版本",
  head_revision: "目标版本",
  heads: "迁移版本",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function canonicalStatus(value: unknown): PlatformReadinessStatus | null {
  return typeof value === "string" && PLATFORM_READINESS_STATUSES.includes(value as PlatformReadinessStatus)
    ? value as PlatformReadinessStatus
    : null;
}

function finiteNonNegative(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function boundedText(value: unknown, maxLength: number, fallback = "未记录"): string {
  if (typeof value !== "string") return fallback;
  const normalized = value.trim().replace(/\s+/g, " ");
  if (!normalized) return fallback;
  return normalized.slice(0, maxLength);
}

function observedRows(value: unknown): Array<{ label: string; value: string }> {
  if (!isRecord(value)) return [];
  return Object.entries(value).flatMap(([key, rawValue]) => {
    const label = OBSERVED_LABELS[key] || boundedText(key.replaceAll("_", " "), 48);
    if (Array.isArray(rawValue)) {
      const items = rawValue
        .slice(0, 8)
        .filter((item): item is string => typeof item === "string")
        .map((item) => boundedText(item, 80))
        .filter(Boolean);
      return items.length > 0 ? [{ label, value: items.join(" · ").slice(0, 640) }] : [];
    }
    if (!["string", "number", "boolean"].includes(typeof rawValue)) return [];
    return [{ label, value: boundedText(String(rawValue), 80) }];
  });
}

function mapCheck(value: unknown, index: number): {
  view: PlatformReadinessCheckView;
  structurallyValid: boolean;
} {
  const check = isRecord(value) ? value : {};
  const status = canonicalStatus(check.status);
  const statusCopy = CHECK_COPY[status || "unknown"];
  const id = boundedText(check.id, 80, `unknown-${index + 1}`);
  const label = boundedText(check.label, 120, "未命名检查");
  const durationMs = finiteNonNegative(check.duration_ms);

  return {
    view: {
      id,
      label,
      status: status || "unknown",
      statusLabel: statusCopy.label,
      tone: statusCopy.tone,
      summary: boundedText(check.summary, 240),
      durationMs,
      owner: boundedText(check.owner, 120),
      nextAction: boundedText(check.next_action, 240),
      runbook: boundedText(check.runbook, 180),
      observed: observedRows(check.observed),
    },
    structurallyValid: isRecord(value)
      && typeof check.id === "string"
      && check.id.trim().length > 0
      && typeof check.label === "string"
      && check.label.trim().length > 0
      && status !== null,
  };
}

function unknownView(checks: PlatformReadinessCheckView[] = []): PlatformReadinessView {
  return {
    state: "unknown",
    sourceStatus: null,
    evidenceState: "unknown",
    tone: "unknown",
    title: "平台状态待确认",
    description: "返回的就绪证据不完整或不一致，不能据此判断平台可用。请刷新并按检查项排查。",
    statusLabel: "状态待确认",
    checkedAt: null,
    ageSeconds: null,
    durationMs: null,
    checkCount: checks.length > 0 ? checks.length : null,
    checks,
  };
}

export function mapPlatformReadiness(
  payload: unknown,
  now = new Date(),
): PlatformReadinessView {
  if (
    !isRecord(payload)
    || payload.contract_version !== "operator-platform-readiness.v1"
    || payload.scope !== "platform"
    || !Array.isArray(payload.checks)
  ) {
    return unknownView();
  }

  const mappedChecks = payload.checks.map(mapCheck);
  const checks = mappedChecks
    .map(({ view }) => view)
    .sort((left, right) => {
      const leftRank = left.status === "unknown" ? 3 : STATUS_RANK[left.status];
      const rightRank = right.status === "unknown" ? 3 : STATUS_RANK[right.status];
      return rightRank - leftRank;
    });
  const sourceStatus = canonicalStatus(payload.status);
  const staleAfterSeconds = finiteNonNegative(payload.stale_after_seconds);
  const futureSkewSeconds = finiteNonNegative(payload.future_skew_seconds);
  const durationMs = finiteNonNegative(payload.duration_ms);
  const checkedAt = typeof payload.checked_at === "string" ? payload.checked_at : "";
  const checkedAtMs = Date.parse(checkedAt);
  const nowMs = now.getTime();
  const identifiers = mappedChecks.map(({ view }) => view.id);
  const checksValid = mappedChecks.length > 0
    && mappedChecks.every(({ structurallyValid }) => structurallyValid)
    && new Set(identifiers).size === identifiers.length;

  if (
    sourceStatus === null
    || staleAfterSeconds === null
    || futureSkewSeconds === null
    || durationMs === null
    || !Number.isFinite(checkedAtMs)
    || !Number.isFinite(nowMs)
    || !checksValid
  ) {
    return { ...unknownView(checks), checkedAt: Number.isFinite(checkedAtMs) ? checkedAt : null };
  }

  const ageSeconds = (nowMs - checkedAtMs) / 1_000;
  if (ageSeconds < -futureSkewSeconds) {
    return {
      ...unknownView(checks),
      checkedAt,
      ageSeconds,
      durationMs,
      checkCount: checks.length,
      description: "检查时间超出允许的时钟偏差，当前证据不能作为平台可用结论。请校准时间后刷新。",
    };
  }

  const mostSevereCheck = mappedChecks.reduce<PlatformReadinessStatus>((worst, { view }) => {
    if (view.status === "unknown") return "unsafe_to_serve";
    return STATUS_RANK[view.status] > STATUS_RANK[worst] ? view.status : worst;
  }, "ready");
  if (STATUS_RANK[sourceStatus] < STATUS_RANK[mostSevereCheck]) {
    return {
      ...unknownView(checks),
      checkedAt,
      ageSeconds,
      durationMs,
      checkCount: checks.length,
      description: "聚合结论与检查项不一致，当前证据不能作为平台可用结论。请刷新并检查就绪服务。",
    };
  }

  if (ageSeconds > staleAfterSeconds) {
    return {
      state: "stale",
      sourceStatus,
      evidenceState: "stale",
      tone: "warning",
      title: "就绪证据已过期",
      description: "上次检查结果已超过有效时间，不能据此继续判断平台可用。请立即刷新。",
      statusLabel: "证据已过期",
      checkedAt,
      ageSeconds,
      durationMs,
      checkCount: checks.length,
      checks,
    };
  }

  return {
    state: sourceStatus,
    sourceStatus,
    evidenceState: "fresh",
    ...READINESS_COPY[sourceStatus],
    checkedAt,
    ageSeconds,
    durationMs,
    checkCount: checks.length,
    checks,
  };
}

export function formatReadinessDuration(value: number | null): string {
  if (value === null) return "未记录";
  if (value < 1) return `${Number(value.toFixed(2))}ms`;
  return `${Math.round(value)}ms`;
}

export function formatReadinessTime(value: string | null): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "未记录" : date.toLocaleString("zh-CN");
}

export function formatEvidenceAge(value: number | null): string {
  if (value === null || value < 0) return "未记录";
  if (value < 60) return `${Math.floor(value)} 秒前`;
  if (value < 3_600) return `${Math.floor(value / 60)} 分钟前`;
  return `${Math.floor(value / 3_600)} 小时前`;
}
