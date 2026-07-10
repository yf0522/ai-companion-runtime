"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { ErrorState, LoadingState } from "@/components/SurfaceStates";
import { ApiError, fetchTrace, userFacingApiError } from "@/lib/api-client";

interface TraceEvent {
  step_name?: string;
  step_index?: number;
  status?: string;
  latency_ms?: number | null;
  output?: unknown;
  error?: string | null;
}

interface ModelCall {
  provider?: string;
  model?: string;
  role?: string;
  prompt_tokens?: number;
  output_tokens?: number;
  ttft_ms?: number;
  total_latency_ms?: number;
  status?: string;
  cost_cents?: number;
}

interface ToolCallData {
  tool_name?: string;
  status?: string;
  latency_ms?: number;
}

interface TraceData {
  trace_id?: string;
  user_id?: string | null;
  session_id?: string | null;
  started_at?: string | null;
  total_latency_ms?: number | null;
  events?: TraceEvent[];
  model_calls?: ModelCall[];
  tool_calls?: ToolCallData[];
  cost_summary?: {
    total_tokens?: number;
    total_cost_cents?: number;
  };
}

const stepLabels: Record<string, string> = {
  ws_receive: "消息接收",
  intent_detection: "意图识别",
  emotion_detection: "情绪识别",
  risk_detection: "风险识别",
  memory_recall: "记忆召回",
  personality_adapt: "人格适配",
  fast_reply_race: "快速回复竞赛",
  prompt_build: "Prompt 构建",
  model_stream: "模型流式输出",
  tool_call: "工具调用",
  response_final: "最终响应",
  memory_update: "记忆更新",
};

function statusTone(status: string | undefined): string {
  if (status === "success" || status === "completed") return "border-status-success bg-status-success-soft text-ink";
  if (status === "failed" || status === "error") return "border-status-critical bg-status-critical-soft text-ink";
  if (status === "timeout") return "border-status-warning bg-status-warning-soft text-ink";
  return "border-status-unknown bg-status-unknown-soft text-ink";
}

function preview(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function OpsTracePage({ params }: { params: { traceId: string } }) {
  const [trace, setTrace] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchTrace(params.traceId);
        if (!cancelled) setTrace(data);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        if (!cancelled) {
          setError(
            err instanceof ApiError && err.status === 404
              ? "没有找到这条追踪记录。"
              : userFacingApiError(err, "追踪详情加载失败，请稍后重试。"),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [params.traceId, router]);

  return (
    <RoleShell
      role="operator"
      title="追踪详情"
      subtitle={params.traceId}
    >
      {loading && <LoadingState label="正在加载追踪详情" />}
      {error && <ErrorState description={error} />}
      {trace !== null && <TraceWorkspace trace={trace as TraceData} fallbackTraceId={params.traceId} />}
    </RoleShell>
  );
}

function TraceWorkspace({ trace, fallbackTraceId }: { trace: TraceData; fallbackTraceId: string }) {
  const events = Array.isArray(trace.events) ? trace.events : [];
  const modelCalls = Array.isArray(trace.model_calls) ? trace.model_calls : [];
  const toolCalls = Array.isArray(trace.tool_calls) ? trace.tool_calls : [];
  const failedEvents = events.filter((event) => event.status && event.status !== "success").length;
  const owner = failedEvents > 0 ? "运营值班 · 故障复核" : "运营值班 · 抽查";
  const nextAction = failedEvents > 0 ? "优先查看失败步骤、错误内容和下游投递影响。" : "抽查模型、工具和成本证据，确认链路可解释。";

  return (
    <div className="grid gap-4">
      <section className={`border p-4 ${failedEvents > 0 ? "border-status-critical bg-status-critical-soft" : "border-status-info bg-status-info-soft"}`}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Trace Command</p>
            <h2 className="mt-1 break-all text-lg font-semibold text-ink">{trace.trace_id || fallbackTraceId}</h2>
            <p className="mt-2 text-sm text-muted">{nextAction}</p>
          </div>
          <div className="text-sm">
            <div className="font-medium text-ink">{owner}</div>
            <div className="mt-1 text-muted">{trace.started_at || "start time unknown"}</div>
          </div>
        </div>
      </section>

      <section className="grid gap-0 border border-border bg-surface sm:grid-cols-2 lg:grid-cols-5">
        <Metric label="总延迟" value={`${trace.total_latency_ms || 0}ms`} />
        <Metric label="事件" value={`${events.length}`} />
        <Metric label="异常" value={`${failedEvents}`} />
        <Metric label="Token" value={`${trace.cost_summary?.total_tokens || 0}`} />
        <Metric label="成本" value={`¥${((trace.cost_summary?.total_cost_cents || 0) / 100).toFixed(4)}`} />
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.8fr)]">
        <div className="grid content-start gap-3">
          <div className="border-b border-border pb-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Evidence Timeline</p>
            <h2 className="text-lg font-semibold text-ink">链路步骤</h2>
          </div>
          {events.map((event, index) => {
            const eventPreview = preview(event.output);
            return (
              <article key={`${event.step_index || index}-${event.step_name || "step"}`} className="border-l-4 border-primary bg-surface p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold text-ink">
                        [{event.step_index ?? index}] {stepLabels[event.step_name || ""] || event.step_name || "未知步骤"}
                      </h3>
                      <span className={`border px-2 py-0.5 text-xs font-semibold ${statusTone(event.status)}`}>{event.status || "unknown"}</span>
                    </div>
                    <p className="mt-1 text-sm text-muted">latency {event.latency_ms != null ? `${event.latency_ms}ms` : "unknown"}</p>
                  </div>
                </div>
                {event.error && <p className="mt-2 border border-status-critical bg-status-critical-soft px-3 py-2 text-sm text-ink">{event.error}</p>}
                {eventPreview && (
                  <pre className="mt-3 max-h-40 overflow-auto border border-border bg-canvas p-3 text-xs leading-5 text-muted">
                    {eventPreview}
                  </pre>
                )}
              </article>
            );
          })}
        </div>

        <div className="grid content-start gap-4">
          <section className="border border-border bg-surface p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Ownership</p>
            <dl className="mt-3 grid gap-3 text-sm">
              <div>
                <dt className="text-xs text-muted">负责人</dt>
                <dd className="font-medium text-ink">{owner}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">用户</dt>
                <dd className="font-mono text-xs text-ink">{trace.user_id || "unknown"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">会话</dt>
                <dd className="font-mono text-xs text-ink">{trace.session_id || "unknown"}</dd>
              </div>
            </dl>
          </section>

          {modelCalls.length > 0 && (
            <section className="border border-border bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Model Evidence</p>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border text-xs text-muted">
                    <tr>
                      <th className="py-2 pr-3">模型</th>
                      <th className="py-2 pr-3">延迟</th>
                      <th className="py-2 pr-3">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelCalls.map((call, index) => (
                      <tr key={`${call.provider || "provider"}-${call.model || index}`} className="border-b border-border last:border-b-0">
                        <td className="py-2 pr-3">
                          <div className="font-medium text-ink">{call.model || "unknown"}</div>
                          <div className="text-xs text-muted">{call.provider || "unknown"} · {call.role || "role unknown"}</div>
                        </td>
                        <td className="py-2 pr-3 text-muted">{call.total_latency_ms || 0}ms</td>
                        <td className="py-2 pr-3">
                          <span className={`border px-2 py-0.5 text-xs ${statusTone(call.status)}`}>{call.status || "unknown"}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {toolCalls.length > 0 && (
            <section className="border border-border bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Tool Evidence</p>
              <div className="mt-3 grid gap-2">
                {toolCalls.map((call, index) => (
                  <div key={`${call.tool_name || "tool"}-${index}`} className="flex items-center justify-between gap-3 border-b border-border pb-2 text-sm last:border-b-0 last:pb-0">
                    <span className="font-medium text-ink">{call.tool_name || "unknown tool"}</span>
                    <span className="text-muted">{call.latency_ms || 0}ms · {call.status || "unknown"}</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-b border-border p-4 sm:border-r lg:border-b-0">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-lg font-semibold text-ink">{value}</div>
    </div>
  );
}
