export function assistantErrorMessage(event) {
  if (event?.type !== "message_end" || event.message?.role !== "assistant") {
    return null;
  }
  if (event.message.stopReason !== "error") return null;
  return event.message.errorMessage || "pi model returned an error";
}
