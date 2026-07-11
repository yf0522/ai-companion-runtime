export function authoritativeToolShouldTerminate(toolName, status) {
  return (
    careTaskShouldTerminate(toolName, status) ||
    (toolName === "contact" && status === "success")
  );
}

export function careTaskShouldTerminate(toolName, status) {
  return toolName === "caretask" && status === "success";
}

export function authoritativeToolResultText(event) {
  if (!event || event.type !== "tool_result") return "";
  if (
    event.tool !== "contact" &&
    !authoritativeToolShouldTerminate(event.tool, event.status)
  ) return "";
  return String(event.text || "").trim();
}
