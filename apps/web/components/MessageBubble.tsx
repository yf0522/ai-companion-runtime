import type { Message } from "@/stores/chatStore";
import CareTaskClarifyCard, {
  type CareTaskCandidate,
} from "./CareTaskClarifyCard";

interface Props {
  message: Message;
  isStreaming?: boolean;
  onClarifySelect?: (candidate: CareTaskCandidate, verb: string) => void;
}

function RiskAlertBanner({
  message,
  content,
}: {
  message?: string;
  content: string;
}) {
  const alertMsg = (message || "").trim();
  const body = (content || "").trim();
  // Elder UI: never show raw "风险等级：high". Prefer hotline body only;
  // empty risk_alert.message means safety copy already went via first_reply.
  if (!alertMsg) {
    return null;
  }
  // Avoid rendering the same safety paragraph twice in one bubble.
  if (alertMsg === body) {
    return null;
  }
  return (
    <div className="mb-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      {alertMsg}
    </div>
  );
}

export default function MessageBubble({
  message,
  isStreaming = false,
  onClarifySelect,
}: Props) {
  const isUser = message.role === "user";
  const clarify = message.careTaskClarify;

  return (
    <div className={`py-4 ${!isUser ? "bg-[#fafafa]" : ""}`}>
      <div className="mx-auto flex max-w-3xl gap-3.5 px-4">
        {/* Avatar */}
        <div
          className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
            isUser ? "bg-primary-soft text-primary-strong" : "bg-primary text-white"
          }`}
        >
          {isUser ? "U" : "C"}
        </div>

        {/* Body */}
        <div className="min-w-0 flex-1">
          <div className="mb-1 text-[13px] font-semibold text-ink">
            {isUser ? "你" : "陪伴助手"}
          </div>

          {message.riskAlert && (
            <RiskAlertBanner
              message={message.riskAlert.message}
              content={message.content}
            />
          )}

          {/* Content */}
          <div className="whitespace-pre-wrap text-lg leading-8 text-ink">
            {message.content}
            {message.status === "streaming" && (
              <span
                className="ml-0.5 inline-block h-4 w-0.5 rounded-sm bg-primary"
                style={{ animation: "blink 1s infinite" }}
              />
            )}
          </div>

          {/* CareTask clarify — tap to choose which task to cancel/complete */}
          {!isUser && clarify && clarify.candidates.length > 0 && onClarifySelect && (
            <CareTaskClarifyCard
              candidates={clarify.candidates}
              verb={clarify.verb}
              disabled={isStreaming || message.status === "streaming"}
              onSelect={(c) => onClarifySelect(c, clarify.verb)}
            />
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
