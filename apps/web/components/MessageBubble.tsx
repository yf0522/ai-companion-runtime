import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { ChatMessage, ChatMessageBubble, ChatMessageMetadata } from "@astryxdesign/core/Chat";
import { Text } from "@astryxdesign/core/Text";
import type { Message } from "@/stores/chatStore";
import CareTaskClarifyCard, { type CareTaskCandidate } from "./CareTaskClarifyCard";
import OutcomeReceipt from "./elder/OutcomeReceipt";
import { assistantBodyAfterToolReceipts } from "./elder/outcome-receipt";

interface Props { message: Message; isStreaming?: boolean; onClarifySelect?: (candidate: CareTaskCandidate, verb: string) => void; }
const SAFE_PROVIDER_FAILURE = "我现在暂时无法生成完整回复。提醒和安全功能仍然可用，请稍后再试。";

export function elderSafeMessage(content: string): string {
  const body = content.trim();
  if (!body) return body;
  const technicalFailure = /user location is not supported/i.test(body) || /provider[_\s-]?error/i.test(body) || /model[_\s-]?error/i.test(body) || /status[_\s-]?code/i.test(body) || /"error"\s*:/i.test(body) || /^\s*\{[\s\S]*\}\s*$/.test(body);
  return technicalFailure ? SAFE_PROVIDER_FAILURE : content;
}

export default function MessageBubble({ message, isStreaming = false, onClarifySelect }: Props) {
  const isUser = message.role === "user";
  const assistantContent = assistantBodyAfterToolReceipts(message.content, message.toolsUsed || []);
  const visibleContent = isUser ? message.content : elderSafeMessage(assistantContent);

  if (isUser) {
    return (
      <ChatMessage sender="user" className="companion-message-enter">
        <ChatMessageBubble metadata={message.status === "error" ? <ChatMessageMetadata status="error" /> : undefined}>
          {visibleContent}
        </ChatMessageBubble>
      </ChatMessage>
    );
  }

  return (
    <ChatMessage sender="assistant" avatar={<Avatar name="Companion" size="small" />} name="Companion" className="companion-message-enter">
      {message.riskAlert && (
        <div className="risk-interrupt">
          <Badge label="先暂停当前操作" variant="error" />
          <Text display="block" style={{ marginTop: 8 }}>{message.riskAlert.message}</Text>
        </div>
      )}
      {(message.toolsUsed || []).map((tool, index) => (
        <OutcomeReceipt key={`${tool.tool}-${index}`} tool={tool} />
      ))}
      {(visibleContent || message.status === "streaming") && (
        <ChatMessageBubble
          variant="ghost"
          metadata={message.status === "streaming" ? <ChatMessageMetadata footer={<Text type="supporting">正在组织回复</Text>} /> : undefined}
        >
          <Text as="div" size="lg" style={{ whiteSpace: "pre-wrap", lineHeight: 1.75 }}>{visibleContent || "正在听你说…"}</Text>
        </ChatMessageBubble>
      )}
      {message.careTaskClarify && message.careTaskClarify.candidates.length > 0 && onClarifySelect && (
        <CareTaskClarifyCard candidates={message.careTaskClarify.candidates} verb={message.careTaskClarify.verb} disabled={isStreaming || message.status === "streaming"} onSelect={(candidate) => onClarifySelect(candidate, message.careTaskClarify!.verb)} />
      )}
      {message.status === "error" && <Badge label="消息尚未送达，请重新发送" variant="error" />}
    </ChatMessage>
  );
}
