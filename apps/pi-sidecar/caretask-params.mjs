export function normalizeCareTaskParams(params, userText) {
  const normalized = { ...(params || {}) };
  const text = String(userText || "").trim();
  if (text) normalized.query = text;
  if (normalized.action !== "list") return normalized;

  if (/取消|删除|关掉|不要.*提醒/.test(text)) {
    normalized.action = "cancel";
  } else if (/吃过了|吃了|已吃|完成/.test(text)) {
    normalized.action = "complete";
  }
  return normalized;
}
