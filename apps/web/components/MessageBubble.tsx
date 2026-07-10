import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { ChatMessage, ChatMessageBubble, ChatMessageMetadata, ChatToolCalls, type ChatToolCallItem } from "@astryxdesign/core/Chat";
import { Text } from "@astryxdesign/core/Text";
import type { Message, ToolChipStatus } from "@/stores/chatStore";
import CareTaskClarifyCard, { type CareTaskCandidate } from "./CareTaskClarifyCard";

interface Props { message: Message; isStreaming?: boolean; onClarifySelect?: (candidate: CareTaskCandidate, verb: string) => void; }
const SAFE_PROVIDER_FAILURE = "我现在暂时无法生成完整回复。提醒和安全功能仍然可用，请稍后再试。";

export function elderSafeMessage(content: string): string {
  const body = content.trim();
  if (!body) return body;
  const technicalFailure = /user location is not supported/i.test(body) || /provider[_\s-]?error/i.test(body) || /model[_\s-]?error/i.test(body) || /status[_\s-]?code/i.test(body) || /"error"\s*:/i.test(body) || /^\s*\{[\s\S]*\}\s*$/.test(body);
  return technicalFailure ? SAFE_PROVIDER_FAILURE : content;
}

function toolStatus(status: ToolChipStatus): ChatToolCallItem["status"] {
  if (status === "calling") return "running";
  if (status === "failed" || status === "timeout") return "error";
  if (status === "needs_clarification") return "pending";
  return "complete";
}

export default function MessageBubble({ message, isStreaming = false, onClarifySelect }: Props) {
  const isUser = message.role === "user";
  const visibleContent = isUser ? message.content : elderSafeMessage(message.content);
  const calls: ChatToolCallItem[] = (message.toolsUsed || []).map((tool) => ({
    name: tool.tool,
    status: toolStatus(tool.status),
    target: tool.action || (tool.status === "needs_clarification" ? "等待确认" : "照护运行时"),
    errorMessage: tool.status === "failed" || tool.status === "timeout" ? "工具未成功完成" : undefined,
  }));

  if (isUser) {
    return (
      <ChatMessage sender="user" className="companion-message-enter">
        <ChatMessageBubble metadata={<ChatMessageMetadata status={message.status === "error" ? "error" : "read"} />}>
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
      {calls.length > 0 && <ChatToolCalls calls={calls} label="正在执行照护动作" />}
      <ChatMessageBubble
        variant="ghost"
        metadata={<ChatMessageMetadata footer={<Text type="supporting">{message.totalLatencyMs ? `${message.totalLatencyMs}ms · trace ${message.traceId?.slice(0, 8) || "pending"}` : message.status === "streaming" ? "正在组织回复" : "风险与工具已检查"}</Text>} />}
      >
        <Text as="div" size="lg" style={{ whiteSpace: "pre-wrap", lineHeight: 1.75 }}>{visibleContent || (message.status === "streaming" ? "正在听你说…" : "")}</Text>
      </ChatMessageBubble>
      {message.careTaskClarify && message.careTaskClarify.candidates.length > 0 && onClarifySelect && (
        <CareTaskClarifyCard candidates={message.careTaskClarify.candidates} verb={message.careTaskClarify.verb} disabled={isStreaming || message.status === "streaming"} onSelect={(candidate) => onClarifySelect(candidate, message.careTaskClarify!.verb)} />
      )}
      {message.status === "error" && <Badge label="消息尚未送达，请重新发送" variant="error" />}
    </ChatMessage>
  );
}
