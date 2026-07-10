export function normalizeCareTaskParams(params, userText) {
  const normalized = { ...(params || {}) };
  const text = String(userText || "").trim();
  if (text) normalized.query = text;
  if (normalized.action !== "list") return normalized;

  if (/取消|删除|关掉|不要.*提醒/.test(text)) {
    normalized.action = "cancel";
    return normalized;
  }
  if (/吃过了|吃了|已吃|完成/.test(text)) {
    normalized.action = "complete";
    return normalized;
  }
  // Default list to today's care window for LLM dump (no today_brief tool).
  if (!normalized.scope) normalized.scope = "today";
  return normalized;
}

export function normalizeMemoryParams(params, userText) {
  const normalized = { ...(params || {}) };
  const text = String(userText || "").trim();
  if (text) normalized.query = text;
  if (!normalized.action || normalized.action === "auto") {
    if (/以后记得|帮我记住|记一下我|请记住|别忘了我/.test(text)) {
      normalized.action = "note";
    } else {
      normalized.action = "recall";
    }
  }
  if (normalized.action === "note" && !normalized.summary && text) {
    normalized.summary = text;
  }
  if (normalized.action === "note" && normalized.explicit_user_request == null) {
    normalized.explicit_user_request = /以后记得|帮我记住|记一下|请记住|别忘了/.test(
      text,
    );
  }
  if (normalized.action === "recall" && !normalized.query_intent && text) {
    normalized.query_intent = text;
  }
  return normalized;
}
