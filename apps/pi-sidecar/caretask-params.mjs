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
  const noteRequested = /以后记得|帮我记住|记一下|请记住|别忘了/.test(text);
  if (text) normalized.query = text;
  if (noteRequested) {
    normalized.action = "note";
  } else if (!normalized.action || normalized.action === "auto") {
    normalized.action = "recall";
  }
  if (normalized.action === "note") {
    // Note writes must be grounded in the actual user turn. Never trust a
    // model-supplied summary or explicitness flag for persistence decisions.
    normalized.query = text;
    normalized.summary = text;
    normalized.explicit_user_request = noteRequested;
  }
  if (normalized.action === "recall" && !normalized.query_intent && text) {
    normalized.query_intent = text;
  }
  return normalized;
}

/** Post-FC normalizer for utility (weather|calculator|search). */
export function normalizeUtilityParams(params, userText) {
  const normalized = { ...(params || {}) };
  const text = String(userText || "").trim();
  if (text) normalized.query = text;
  const op = String(normalized.op || normalized.action || "").toLowerCase();
  if (["weather", "calculator", "search"].includes(op)) {
    normalized.op = op;
    return normalized;
  }
  if (/天气|气温|下雨|温度/.test(text)) normalized.op = "weather";
  else if (/等于多少|算一下|计算|[\d]\s*[+\-*/×÷]/.test(text)) normalized.op = "calculator";
  else if (/搜一下|搜索|查一下|百度|谷歌/.test(text)) normalized.op = "search";
  return normalized;
}
