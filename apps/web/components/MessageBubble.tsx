import type { Message, ToolChip, ToolChipStatus } from "@/stores/chatStore";

interface Props {
  message: Message;
}

function chipStyle(status: ToolChipStatus): string {
  switch (status) {
    case "success":
      return "border-green-200 bg-green-50 text-green-700";
    case "needs_clarification":
      return "border-amber-300 bg-amber-50 text-amber-800";
    case "failed":
    case "timeout":
      return "border-rose-200 bg-rose-50 text-rose-700";
    case "calling":
    default:
      return "border-gray-200 bg-gray-50 text-gray-600";
  }
}

function chipLabel(chip: ToolChip): string {
  switch (chip.status) {
    case "success":
      return `${chip.tool} ✓`;
    case "needs_clarification":
      return `${chip.tool} 需要确认`;
    case "failed":
      return `${chip.tool} ×`;
    case "timeout":
      return `${chip.tool} 超时`;
    case "calling":
    default:
      return `${chip.tool} 处理中…`;
  }
}

function RiskAlertBanner({
  level,
  message,
  content,
}: {
  level: string;
  message?: string;
  content: string;
}) {
  const alertMsg = (message || "").trim();
  const body = (content || "").trim();
  // Avoid rendering the same safety paragraph twice in one bubble.
  if (alertMsg && alertMsg === body) {
    return (
      <div className="mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700">
        风险等级：{level}
      </div>
    );
  }
  if (alertMsg) {
    return (
      <div className="mb-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {alertMsg}
      </div>
    );
  }
  return (
    <div className="mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700">
      风险等级：{level}
    </div>
  );
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <div className={`py-4 ${!isUser ? "bg-[#fafafa]" : ""}`}>
      <div className="mx-auto flex max-w-3xl gap-3.5 px-4">
        {/* Avatar */}
        <div
          className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
            isUser
              ? "bg-indigo-100 text-indigo-700"
              : "bg-gradient-to-br from-indigo-500 to-purple-500 text-white"
          }`}
        >
          {isUser ? "U" : "C"}
        </div>

        {/* Body */}
        <div className="min-w-0 flex-1">
          <div className="mb-1 text-[13px] font-semibold text-gray-800">
            {isUser ? "你" : "AI Companion"}
          </div>

          {message.riskAlert && (
            <RiskAlertBanner
              level={message.riskAlert.level}
              message={message.riskAlert.message}
              content={message.content}
            />
          )}

          {/* Content */}
          <div className="whitespace-pre-wrap text-sm leading-[1.7] text-gray-700">
            {message.content}
            {message.status === "streaming" && (
              <span
                className="ml-0.5 inline-block h-4 w-0.5 rounded-sm bg-indigo-500"
                style={{ animation: "blink 1s infinite" }}
              />
            )}
          </div>

          {/* Tool badges — honest states; never green ✓ on clarification/failure */}
          {message.toolsUsed && message.toolsUsed.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {message.toolsUsed.map((chip) => (
                <span
                  key={`${chip.tool}-${chip.status}`}
                  className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] ${chipStyle(chip.status)}`}
                >
                  {chipLabel(chip)}
                </span>
              ))}
            </div>
          )}

          {/* Meta bar */}
          {message.status === "complete" && !isUser && message.ttftMs !== undefined && (
            <div className="mt-2 flex items-center gap-3">
              <button className="flex h-[26px] w-[26px] items-center justify-center rounded-md text-[13px] text-gray-400 transition hover:bg-gray-100 hover:text-gray-600">
                📋
              </button>
              <button className="flex h-[26px] w-[26px] items-center justify-center rounded-md text-[13px] text-gray-400 transition hover:bg-gray-100 hover:text-gray-600">
                🔄
              </button>
              <span className="text-[11px] text-gray-400">
                TTFT: {message.ttftMs}ms
              </span>
              {message.totalLatencyMs !== undefined && (
                <span className="text-[11px] text-gray-400">
                  Total: {message.totalLatencyMs}ms
                </span>
              )}
              {message.traceId && (
                <a
                  href={`/traces/${message.traceId}`}
                  className="text-[11px] text-indigo-500 no-underline hover:underline"
                >
                  查看 Trace →
                </a>
              )}
            </div>
          )}

          {/* Error */}
          {message.status === "error" && (
            <div className="mt-1 text-xs text-red-400">发送失败</div>
          )}
        </div>
      </div>
    </div>
  );
}
