export function normalizeCareTaskParams(params, userText) {
  const normalized = { ...(params || {}) };
  const text = String(userText || "").trim();
  if (text) normalized.query = text;
  const scheduledCandidate = /^(?:请|麻烦|帮我)?(?:(?:今天|明天|后天|每天|每日|每周).{0,24}|(?:早上|上午|中午|下午|傍晚|晚上|夜里|凌晨)?\d{1,2}\s*[点时:](?:\d{1,2}\s*分?)?.{0,8})(?:吃.{0,8}药|服.{0,8}药|复诊|看病|去医院)(?:吧|啊|哦)?$/.test(text);
  const scheduledDirective = text.replace(/^(?:请|麻烦|帮我)/, "");
  const scheduledCreate =
    scheduledCandidate &&
    !scheduledDirective.includes("我") &&
    !/(?:吗|么|呢|如何|怎么|怎样|怎么办)[？?]?$|[？?]$/.test(scheduledDirective) &&
    !/[“”「」『』"']|(?:如果|假如|要是|若|万一|倘若|假设|据说|听说)|(?:新闻|报道|文章|视频).{0,16}(?:提到|说|写|讲)?|(?:医生|家人|别人|他|她|他们|她们).{0,16}(?:吃|服|复诊|看病|去医院)|(?:不要|别|不用|无需|不必|不需要|禁止|没有|并未|没|未)/.test(scheduledDirective);

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

  const mutationCue = /(?:不要|别)(?:再)?提醒我|取消|删除|关掉|不要了|吃过了|吃了(?:药)?|已吃|完成|晚点再|等会儿再|推迟|延后|再提醒|分钟后再|提醒我|帮我记(?:一下|下)|记一下|记下|新增|添加|新建|创建|建立|设置|安排/g;
  const cues = [...text.matchAll(mutationCue)];
  const cue = cues[0];
  const cueIndex = cue?.index ?? -1;
  const prefix = cueIndex >= 0 ? text.slice(0, cueIndex) : "";
  const quoteStack = [];
  const quotePairs = new Map([["“", "”"], ["「", "」"], ["『", "』"], ['"', '"'], ["'", "'"]]);
  for (const character of prefix) {
    if (quoteStack.at(-1) === character) quoteStack.pop();
    else if (quotePairs.has(character)) quoteStack.push(quotePairs.get(character));
  }
  const openQuote = quoteStack.length > 0;
  const unauthorized =
    cues.length !== 1 ||
    openQuote ||
    /(?:不要|别|不用|无需|不必|不需要|禁止|没有|并未|没|未|不是(?:要|想)|不想|不打算|不会).{0,10}$/.test(prefix) ||
    /(?:如果|假如|要是|若|万一|倘若|假设|如何|怎么|怎样|是否|能否|可否|要不要|该不该|会不会|是不是|教程|教我|说明|解释|举例|例子|比如|例如).{0,24}$/.test(prefix) ||
    /(?:(?:新闻|报道|文章|视频)(?:里|中)?(?:提到|说|写|讲)|(?:别人|医生|家人|他|她|他们|她们)(?:让我|叫我|要我|建议我|问我|提到|说|讲)).{0,18}$/.test(prefix) ||
    /(?:吗|么|呢|如何|怎么|怎样|怎么办)[？?]?$|[？?]$/.test(text);

  if (cue && unauthorized) {
    normalized.action = "clarify";
    delete normalized.scope;
    return normalized;
  }

  if (/(?:不要|别)(?:再)?提醒我|取消|删除|关掉|不要了/.test(text)) {
    normalized.action = "cancel";
    return normalized;
  }
  if (/吃过了|吃了|已吃|完成/.test(text)) {
    normalized.action = "complete";
    return normalized;
  }
  if (/晚点再|等会儿再|推迟|延后|再提醒|分钟后再/.test(text)) {
    normalized.action = "snooze";
    return normalized;
  }

  const explicitCreate =
    /提醒我|帮我记(?:一下|下)|记一下|记下|新增|添加|新建|创建|建立|设置|安排/.test(
      text,
    ) || scheduledCreate;
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
