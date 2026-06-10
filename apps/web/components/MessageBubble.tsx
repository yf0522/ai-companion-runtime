import type { Message } from "@/stores/chatStore";

interface Props {
  message: Message;
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-blue-500 text-white rounded-br-md"
            : "bg-gray-100 text-gray-900 rounded-bl-md"
        }`}
      >
        {message.riskAlert && (
          <div className="mb-2 rounded-lg bg-red-50 border border-red-200 p-2 text-sm text-red-700">
            {message.riskAlert.message}
          </div>
        )}

        <p className="whitespace-pre-wrap text-sm leading-relaxed">
          {message.content}
          {message.status === "streaming" && (
            <span className="inline-block w-1.5 h-4 ml-0.5 bg-gray-400 animate-pulse rounded-sm" />
          )}
        </p>

        {message.status === "complete" && message.role === "assistant" && message.ttftMs !== undefined && (
          <div className="mt-2 flex gap-3 text-xs text-gray-400">
            <span>TTFT: {message.ttftMs}ms</span>
            {message.totalLatencyMs !== undefined && (
              <span>Total: {message.totalLatencyMs}ms</span>
            )}
            {message.traceId && (
              <a
                href={`/traces/${message.traceId}`}
                className="underline hover:text-gray-600"
              >
                Trace
              </a>
            )}
          </div>
        )}

        {message.status === "error" && (
          <div className="mt-1 text-xs text-red-400">发送失败</div>
        )}
      </div>
    </div>
  );
}
