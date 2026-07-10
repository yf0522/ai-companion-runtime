export function careTaskShouldTerminate(toolName, status) {
  return toolName === "caretask" && status === "success";
}
