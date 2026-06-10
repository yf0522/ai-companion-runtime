"use client";

interface TraceEvent {
  step_name: string;
  step_index: number;
  status: string;
  latency_ms: number | null;
  input: any;
  output: any;
  error: string | null;
}

interface ModelCall {
  provider: string;
  model: string;
  role: string;
  prompt_tokens: number;
  output_tokens: number;
  ttft_ms: number;
  total_latency_ms: number;
  status: string;
  cost_cents: number;
}

interface ToolCallData {
  tool_name: string;
  status: string;
  latency_ms: number;
}

interface TraceData {
  trace_id: string;
  user_id: string | null;
  session_id: string | null;
  started_at: string | null;
  total_latency_ms: number | null;
  events: TraceEvent[];
  model_calls: ModelCall[];
  tool_calls: ToolCallData[];
  cost_summary: {
    total_tokens: number;
    total_cost_cents: number;
  };
}

interface Props {
  trace: TraceData;
}

const STATUS_COLORS: Record<string, string> = {
  success: "bg-green-100 text-green-700 border-green-200",
  failed: "bg-red-100 text-red-700 border-red-200",
  timeout: "bg-yellow-100 text-yellow-700 border-yellow-200",
  skipped: "bg-gray-100 text-gray-500 border-gray-200",
};

const STEP_LABELS: Record<string, string> = {
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

export default function TraceTimeline({ trace }: Props) {
  const maxLatency = Math.max(
    ...trace.events.map((e) => e.latency_ms || 0),
    1
  );

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <SummaryCard label="总延迟" value={`${trace.total_latency_ms || 0}ms`} />
        <SummaryCard label="事件数" value={`${trace.events.length}`} />
        <SummaryCard label="Token" value={`${trace.cost_summary.total_tokens}`} />
        <SummaryCard
          label="成本"
          value={`¥${(trace.cost_summary.total_cost_cents / 100).toFixed(4)}`}
        />
      </div>

      {/* Event Timeline */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-600">事件链路</h3>
        {trace.events.map((event, i) => (
          <div key={i} className="flex items-start gap-3">
            {/* Timeline dot */}
            <div className="flex flex-col items-center">
              <div
                className={`h-3 w-3 rounded-full ${
                  event.status === "success" ? "bg-green-400" : "bg-red-400"
                }`}
              />
              {i < trace.events.length - 1 && (
                <div className="h-8 w-px bg-gray-200" />
              )}
            </div>

            {/* Event card */}
            <div className="flex-1 rounded-lg border border-gray-100 bg-white p-3 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-800">
                    [{event.step_index}] {STEP_LABELS[event.step_name] || event.step_name}
                  </span>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      STATUS_COLORS[event.status] || STATUS_COLORS.skipped
                    }`}
                  >
                    {event.status}
                  </span>
                </div>
                <span className="text-xs text-gray-400">
                  {event.latency_ms != null ? `${event.latency_ms}ms` : "--"}
                </span>
              </div>

              {/* Latency bar */}
              {event.latency_ms != null && (
                <div className="mt-2 h-1.5 rounded-full bg-gray-100">
                  <div
                    className="h-1.5 rounded-full bg-blue-400"
                    style={{
                      width: `${Math.max(2, (event.latency_ms / maxLatency) * 100)}%`,
                    }}
                  />
                </div>
              )}

              {/* Output preview */}
              {event.output && (
                <pre className="mt-2 max-h-24 overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-600">
                  {JSON.stringify(event.output, null, 2)}
                </pre>
              )}

              {event.error && (
                <p className="mt-1 text-xs text-red-500">{event.error}</p>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Model Calls */}
      {trace.model_calls.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-gray-600">模型调用</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-gray-500">
                  <th className="py-2">Provider</th>
                  <th>Model</th>
                  <th>Role</th>
                  <th>TTFT</th>
                  <th>总延迟</th>
                  <th>Token</th>
                  <th>成本</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {trace.model_calls.map((mc, i) => (
                  <tr key={i} className="border-b">
                    <td className="py-2">{mc.provider}</td>
                    <td>{mc.model}</td>
                    <td>{mc.role}</td>
                    <td>{mc.ttft_ms}ms</td>
                    <td>{mc.total_latency_ms}ms</td>
                    <td>{mc.prompt_tokens + mc.output_tokens}</td>
                    <td>¥{(mc.cost_cents / 100).toFixed(4)}</td>
                    <td>
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs ${
                          mc.status === "success"
                            ? "bg-green-100 text-green-700"
                            : "bg-red-100 text-red-700"
                        }`}
                      >
                        {mc.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tool Calls */}
      {trace.tool_calls.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-gray-600">工具调用</h3>
          <div className="flex flex-wrap gap-3">
            {trace.tool_calls.map((tc, i) => (
              <div
                key={i}
                className="rounded-lg border bg-white p-3 shadow-sm"
              >
                <div className="font-medium text-sm">{tc.tool_name}</div>
                <div className="mt-1 flex gap-2 text-xs text-gray-500">
                  <span>{tc.latency_ms}ms</span>
                  <span
                    className={
                      tc.status === "success" ? "text-green-600" : "text-red-600"
                    }
                  >
                    {tc.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-gray-800">{value}</div>
    </div>
  );
}
