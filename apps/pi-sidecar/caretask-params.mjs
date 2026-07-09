export function normalizeCareTaskParams(params, userText) {
  const normalized = { ...(params || {}) };
  if (normalized.action !== "list") return normalized;

  const text = String(userText || "").trim();
  if (/取消|删除|关掉|不要.*提醒/.test(text)) {
    normalized.action = "cancel";
    normalized.query = normalized.query || normalized.title || text;
  } else if (/吃过了|吃了|已吃|完成/.test(text)) {
    normalized.action = "complete";
    normalized.query = normalized.query || normalized.title || text;
  }
  return normalized;
}
