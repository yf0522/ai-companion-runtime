export const ASSISTANT_ERROR_MESSAGE = "服务暂时不可用，请稍后再试。";

export function assistantErrorMessage(event) {
  if (event?.type !== "message_end" || event.message?.role !== "assistant") {
    return null;
  }
  if (event.message.stopReason !== "error") return null;
  return ASSISTANT_ERROR_MESSAGE;
}
