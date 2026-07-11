export function normalizeCareTaskParams(params, userText) {
  const normalized = { ...(params || {}) };
  const text = String(userText || "").trim();
  if (text) normalized.query = text;

  const readOnly =
    /有哪些|有什么|列出|查看|看看|查一下|我的.*任务|待办|还没吃/.test(
      text,
    ) ||
    /今日(?:事项|任务)|今天.*(?:任务|事项|安排)|今天需要做什么|需要做什么/.test(
      text,
    );
  if (readOnly) {
    normalized.action = "list";
    if (!normalized.scope) normalized.scope = "today";
    return normalized;
  }

  if (/取消|删除|关掉|不要.*提醒/.test(text)) {
    normalized.action = "cancel";
    return normalized;
  }
  if (/吃过了|吃了|已吃|完成/.test(text)) {
    normalized.action = "complete";
    return normalized;
  }
  if (/晚点再|等会儿再|推迟|再提醒|分钟后再/.test(text)) {
    normalized.action = "snooze";
    return normalized;
  }

  const explicitCreate =
    /提醒我|帮我记(?:一下|下)|记一下|记下|新增|添加|新建|创建|建立|设置|安排/.test(
      text,
    ) ||
    /(?:每天|每日|每周|明天|后天).*(?:吃药|服药|复诊|任务|提醒)/.test(
      text,
    ) ||
    /\d{1,2}\s*[点时:].*(?:吃药|服药|复诊|任务|提醒)/.test(text);
  if (explicitCreate) {
    normalized.action = "create";
    return normalized;
  }

  // A care-domain write must be grounded in an explicit cue from the actual
  // user turn. Model-selected create/complete/cancel/snooze values are not
  // sufficient authorization, so ambiguous and read-only turns fail safe to
  // today's list instead of creating or mutating a task.
  normalized.action = "list";
  // Default list to today's care window for LLM dump (no today_brief tool).
  if (!normalized.scope) normalized.scope = "today";
  return normalized;
}

export function normalizeContactParams(_params, userText) {
  // Contact is a side effect: the model may choose only the tool. The bridge
  // receives the raw user turn and trusted runtime context, never a model-
  // selected recipient, identity, delivery channel, or rewritten summary.
  return {
    action: "request_contact",
    query: String(userText || "").trim(),
  };
}

export function isExplicitFamilyContactRequest(userText) {
  const text = String(userText || "").trim();
  if (!text || /不用|不要|不需要|不想/.test(text)) return false;
  const family = "(?:家人|家属|孩子|女儿|儿子)";
  if (new RegExp(`(?:联系|通知|告诉).{0,6}${family}.{0,4}(?:了吗|了没|过吗|没有)$`).test(text)) {
    return false;
  }
  return (
    new RegExp(
      `^(?:请|麻烦|帮我|能不能|可以)?(?:联系|通知|告诉).{0,4}${family}`,
    ).test(text) ||
    new RegExp(
      `^(?:请|麻烦|帮我|让|我想让|想让|希望|我希望|需要|我需要|能不能让|可以让).{0,6}${family}.{0,12}(?:联系我|给我打电话|知道我需要帮助|来帮我|帮帮我|来看看我)`,
    ).test(text) ||
    new RegExp(
      `^(?:(?:我希望|我想).{0,4}你|(?:请|麻烦).{0,4}(?:你)?)(?:联系|通知|告诉).{0,4}${family}`,
    ).test(text)
  );
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
