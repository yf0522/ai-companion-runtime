"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ExternalLink, FileClock, ShieldCheck, TriangleAlert } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchTrace,
  type TraceDetailResponse,
  type TraceEventData,
  userFacingApiError,
} from "@/lib/api-client";
import {
  formatRecordedMetric,
  isFailedTraceStatus,
  traceStatusLabel,
} from "../../_lib/operator";
import styles from "../../operator.module.css";

const stepLabels: Record<string, string> = {
  ws_receive: "消息接收",
  intent_detection: "意图识别",
  emotion_detection: "情绪识别",
  risk_detection: "风险识别",
  memory_recall: "记忆召回",
  personality_adapt: "回应适配",
  fast_reply_race: "快速回复",
  prompt_build: "上下文构建",
  model_stream: "模型输出",
  tool_call: "照护动作",
  response_final: "最终回应",
  memory_update: "记忆更新",
};

function formatTime(value: string | null | undefined): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间待确认" : date.toLocaleString("zh-CN");
}

function preview(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function eventKey(event: TraceEventData, index: number): string {
  return `${event.step_index ?? index}-${event.step_name || "step"}-${index}`;
}

export default function OpsTracePage() {
  const params = useParams<{ traceId: string }>();
  const traceId = params.traceId;
  const [trace, setTrace] = useState<TraceDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchTrace(traceId);
        if (!cancelled) setTrace(data);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        if (!cancelled) {
          setError(
            err instanceof ApiError && err.status === 404
              ? "没有找到可由当前案件授权查看的追踪记录。"
              : userFacingApiError(err, "追踪详情加载失败，请稍后重试。"),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [router, traceId]);

  return (
    <RoleShell role="operator" title="追踪详情" subtitle="打开详情会写入案件审计记录">
      <div className={styles.workspace}>
        <header className={styles.pageHeader}>
          <div><h2>运行证据</h2><p>异常步骤优先展示；原始输出默认折叠，缺失指标明确显示为“未记录”。</p></div>
          <a className={styles.contextLink} href="/ops/traces">返回追踪列表</a>
        </header>
        {loading && <LoadingState label="正在加载追踪详情" />}
        {error && <ErrorState description={error} />}
        {trace && <TraceWorkspace trace={trace} fallbackTraceId={traceId} />}
      </div>
    </RoleShell>
  );
}

function TraceWorkspace({ trace, fallbackTraceId }: { trace: TraceDetailResponse; fallbackTraceId: string }) {
  const events = Array.isArray(trace.events) ? trace.events : [];
  const modelCalls = Array.isArray(trace.model_calls) ? trace.model_calls : [];
  const toolCalls = Array.isArray(trace.tool_calls) ? trace.tool_calls : [];
  const failedEvents = events.filter((event) => isFailedTraceStatus(event.status));
  const orderedEvents = [
    ...failedEvents,
    ...events.filter((event) => !isFailedTraceStatus(event.status)),
  ];
  const authorization = trace.authorization;
  const totalTokens = trace.cost_summary?.total_tokens;
  const costCents = trace.cost_summary?.total_cost_cents;

  return (
    <>
      <section className={styles.commandPanel} data-severity={failedEvents.length > 0 ? "critical" : "normal"}>
        <div className={styles.commandHeader}>
          <div>
            <span className={styles.contextLabel}>Trace</span>
            <h2 className={styles.traceHeading}>{trace.trace_id || fallbackTraceId}</h2>
            <p className={styles.traceLead}>
              {failedEvents.length > 0
                ? "先核对失败步骤、错误内容和对案件处置的影响。"
                : "链路没有已记录的失败状态，仍需按案件需要抽查证据。"}
            </p>
          </div>
          <div className={styles.badgeRow}>
            <span className={styles.badge} data-tone={failedEvents.length > 0 ? "critical" : "success"}>{failedEvents.length > 0 ? <TriangleAlert size={14} /> : <ShieldCheck size={14} />}{failedEvents.length > 0 ? `${failedEvents.length} 个异常步骤` : "无已记录异常"}</span>
            <span className={styles.badge}>{authorization?.scope === "operator_case" ? "案件授权" : "权限待确认"}</span>
          </div>
        </div>
        <div className={styles.commandActions}>
          {(authorization?.case_ids || []).map((caseId) => (
            <a key={caseId} className={styles.contextLink} href={`/ops/care/${caseId}`}>返回案件 {caseId.slice(0, 8)}… <ExternalLink size={14} /></a>
          ))}
        </div>
      </section>

      <section className={styles.metricGrid} aria-label="追踪指标">
        <div><span>总延迟</span><strong>{formatRecordedMetric(trace.total_latency_ms, "ms")}</strong></div>
        <div><span>事件</span><strong>{events.length}</strong></div>
        <div><span>异常</span><strong>{failedEvents.length}</strong></div>
        <div><span>Token</span><strong>{formatRecordedMetric(totalTokens)}</strong></div>
        <div><span>成本记录</span><strong>{costCents == null ? "未记录" : `${costCents.toFixed(4)}¢`}</strong></div>
      </section>

      <div className={styles.detailGrid}>
        <section className={styles.timelinePanel}>
          <div className={styles.sectionHeading}>
            <div><h2>链路步骤</h2><p>{failedEvents.length > 0 ? "异常置顶，原始步骤序号保持不变。" : "按记录顺序展示完整链路。"}</p></div>
            <FileClock size={20} aria-hidden="true" />
          </div>
          {orderedEvents.length === 0 ? (
            <EmptyState title="没有记录到链路步骤" description="这不是零延迟或成功状态；当前 Trace 只有标识，没有可展示事件。" />
          ) : (
            <div className={styles.timeline}>
              {orderedEvents.map((event, index) => {
                const output = preview(event.output);
                const failed = isFailedTraceStatus(event.status);
                return (
                  <article key={eventKey(event, index)} className={styles.timelineItem}>
                    <span className={`${styles.timelineDot} ${failed ? styles.timelineDotCritical : ""}`} aria-hidden="true" />
                    <div className={styles.timelineBody}>
                      <h3>[{event.step_index ?? "?"}] {stepLabels[event.step_name || ""] || event.step_name || "未知步骤"} · {traceStatusLabel(event.status)}</h3>
                      <p>延迟 {formatRecordedMetric(event.latency_ms, "ms")}{event.error ? ` · ${event.error}` : ""}</p>
                      {output && (
                        <details className={styles.rawDetails}>
                          <summary>查看原始步骤输出</summary>
                          <pre>{output}</pre>
                        </details>
                      )}
                    </div>
                    <span className={styles.timelineTime}>{failed ? "需复核" : "已记录"}</span>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <aside className={styles.detailAside}>
          <section className={styles.evidencePanel}>
            <div className={styles.sectionHeading}><div><h2>授权与上下文</h2><p>查看行为已写入关联案件。</p></div></div>
            <dl className={styles.evidenceCard}>
              <div><dt>审计状态</dt><dd>{authorization?.audited ? "已写入案件活动" : "未记录"}</dd></div>
              <div><dt>开始时间</dt><dd>{formatTime(trace.started_at)}</dd></div>
              <div><dt>用户标识</dt><dd>{trace.user_id || "未记录"}</dd></div>
              <div><dt>会话标识</dt><dd>{trace.session_id || "未记录"}</dd></div>
            </dl>
          </section>

          <section className={styles.evidencePanel}>
            <div className={styles.sectionHeading}><div><h2>模型调用</h2><p>缺失延迟、Token 或成本不会显示为零。</p></div></div>
            {modelCalls.length === 0 ? <p className={styles.cellHint}>没有记录到模型调用。</p> : (
              <div className={styles.traceList}>
                {modelCalls.map((call, index) => (
                  <article className={styles.evidenceCard} key={`${call.provider || "provider"}-${call.model || index}`}>
                    <h3>{call.model || "模型未记录"}</h3>
                    <dl>
                      <div><dt>提供方 / 角色</dt><dd>{call.provider || "未记录"} · {call.role || "未记录"}</dd></div>
                      <div><dt>总延迟</dt><dd>{formatRecordedMetric(call.total_latency_ms, "ms")}</dd></div>
                      <div><dt>首字延迟</dt><dd>{formatRecordedMetric(call.ttft_ms, "ms")}</dd></div>
                      <div><dt>状态</dt><dd>{traceStatusLabel(call.status)}</dd></div>
                    </dl>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className={styles.evidencePanel}>
            <div className={styles.sectionHeading}><div><h2>工具调用</h2><p>只展示已记录的工具证据。</p></div></div>
            {toolCalls.length === 0 ? <p className={styles.cellHint}>没有记录到工具调用。</p> : (
              <div className={styles.traceList}>
                {toolCalls.map((call, index) => (
                  <article className={styles.evidenceCard} key={`${call.tool_name || "tool"}-${index}`}>
                    <h3>{call.tool_name || "工具未记录"}</h3>
                    <p className={styles.callMeta}>{traceStatusLabel(call.status)} · {formatRecordedMetric(call.latency_ms, "ms")}</p>
                  </article>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}
