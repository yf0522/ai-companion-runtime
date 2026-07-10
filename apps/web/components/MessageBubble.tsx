import { Bot, ShieldAlert, UserRound } from "lucide-react";
import type { Message } from "@/stores/chatStore";
import CareTaskClarifyCard, {
  type CareTaskCandidate,
} from "./CareTaskClarifyCard";

interface Props {
  message: Message;
  isStreaming?: boolean;
  onClarifySelect?: (candidate: CareTaskCandidate, verb: string) => void;
}

const SAFE_PROVIDER_FAILURE =
  "我现在暂时无法生成完整回复。提醒和安全功能仍然可用，请稍后再试。";

export function elderSafeMessage(content: string): string {
  const body = content.trim();
  if (!body) return body;

  const technicalFailure =
    /user location is not supported/i.test(body) ||
    /provider[_\s-]?error/i.test(body) ||
    /model[_\s-]?error/i.test(body) ||
    /status[_\s-]?code/i.test(body) ||
    /"error"\s*:/i.test(body) ||
    /^\s*\{[\s\S]*\}\s*$/.test(body);

  return technicalFailure ? SAFE_PROVIDER_FAILURE : content;
}

function RiskAlertBanner({ message, content }: { message?: string; content: string }) {
  const alertMessage = (message || "").trim();
  const body = content.trim();
  if (!alertMessage || alertMessage === body) return null;

  return (
    <div className="mb-3 flex gap-3 rounded-md border border-status-critical bg-status-critical-soft p-4 text-base leading-7 text-ink">
      <ShieldAlert className="mt-1 shrink-0" size={20} aria-hidden="true" />
      <div>
        <div className="font-semibold">先暂停当前操作</div>
        <div>{alertMessage}</div>
      </div>
    </div>
  );
}

export default function MessageBubble({ message, isStreaming = false, onClarifySelect }: Props) {
  const isUser = message.role === "user";
  const clarify = message.careTaskClarify;
  const visibleContent = isUser ? message.content : elderSafeMessage(message.content);
  const Icon = isUser ? UserRound : Bot;

  return (
    <article className={`border-t border-border py-5 first:border-t-0 ${isUser ? "bg-surface" : "bg-[#f8fbfa]"}`}>
      <div className="mx-auto flex max-w-3xl gap-3 px-4 sm:gap-4">
        <div className={`mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${isUser ? "bg-primary-soft text-primary-strong" : "bg-[#10201d] text-white"}`}>
          <Icon size={18} aria-hidden="true" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="mb-1 text-sm font-semibold text-ink">{isUser ? "你" : "陪伴助手"}</div>
          {message.riskAlert && (
            <RiskAlertBanner message={message.riskAlert.message} content={visibleContent} />
          )}
          <div className="whitespace-pre-wrap text-lg leading-8 text-ink">
            {visibleContent}
            {message.status === "streaming" && (
              <span className="ml-1 inline-block h-4 w-0.5 rounded-sm bg-primary" style={{ animation: "blink 1s infinite" }} />
            )}
          </div>

          {!isUser && clarify && clarify.candidates.length > 0 && onClarifySelect && (
            <CareTaskClarifyCard
              candidates={clarify.candidates}
              verb={clarify.verb}
              disabled={isStreaming || message.status === "streaming"}
              onSelect={(candidate) => onClarifySelect(candidate, clarify.verb)}
            />
          )}

          {message.status === "error" && (
            <div className="mt-2 text-sm font-medium text-status-critical">消息尚未送达，请重新发送。</div>
          )}
        </div>
      </div>
    </article>
  );
}
