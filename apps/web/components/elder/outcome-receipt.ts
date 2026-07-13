import type { ToolChip } from "@/stores/chatStore";

export type OutcomeReceiptTone = "loading" | "info" | "success" | "pending" | "error";

export interface OutcomeReceiptModel {
  title: string;
  detail: string;
  tone: OutcomeReceiptTone;
}

export function assistantBodyAfterToolReceipts(
  content: string,
  tools: Pick<ToolChip, "status" | "action" | "displayText">[],
): string {
  const body = content.trim();
  if (!body) return content;

  const repeatedByAuthoritativeTool = tools.some((tool) =>
    ["success", "failed", "timeout", "cancelled", "interrupted"].includes(tool.status) &&
    !tool.action?.toLowerCase().includes("list") &&
    tool.displayText?.trim() === body,
  );
  return repeatedByAuthoritativeTool ? "" : content;
}

function safeDetail(value: string | undefined, fallback: string): string {
  const detail = value?.trim();
  if (!detail) return fallback;
  if (
    /(?:caretask|tool[_\s-]?result|provider[_\s-]?error|status[_\s-]?code|trace[_\s-]?id)/i.test(detail) ||
    /^\s*\{[\s\S]*\}\s*$/.test(detail)
  ) {
    return fallback;
  }
  return detail;
}

function actionIncludes(action: string, values: string[]): boolean {
  return values.some((value) => action.includes(value));
}

function batchReceiptDetail(data: Record<string, unknown>): string | undefined {
  if (!Array.isArray(data.receipts)) return undefined;
  const maxReceipts = 20;
  const maxTitleChars = 120;
  const actionLabels: Record<string, string> = {
    list: "查看",
    create: "记下",
    snooze: "推迟",
    complete: "完成",
    cancel: "取消",
    clarify: "确认",
  };
  const statusLabels: Record<string, string> = {
    completed: "已完成",
    failed: "未完成",
    unattempted: "未执行",
    planned: "待执行",
    needs_clarification: "需要确认",
  };
  const lines = data.receipts.slice(0, maxReceipts).flatMap((raw, position) => {
    if (!raw || typeof raw !== "object") return [];
    const receipt = raw as Record<string, unknown>;
    const status = statusLabels[String(receipt.status || "")];
    if (!status) return [];
    const action = actionLabels[String(receipt.action || "")] || `第 ${position + 1} 项`;
    const result = receipt.result && typeof receipt.result === "object" && !Array.isArray(receipt.result)
      ? receipt.result as Record<string, unknown>
      : {};
    const titles = Array.isArray(result.titles)
      ? result.titles
        .filter((title): title is string => typeof title === "string" && Boolean(title.trim()))
        .slice(0, 10)
      : [];
    const rawTitle = typeof result.title === "string" && result.title.trim()
      ? result.title.trim()
      : titles.join("、");
    const title = rawTitle.slice(0, maxTitleChars);
    const detail = title ? `（${title}）` : "";
    const index = typeof receipt.index === "number" ? receipt.index + 1 : position + 1;
    return [`${index}. ${action}${detail}：${status}`];
  });
  return lines.length ? lines.join("\n") : undefined;
}

export function outcomeReceiptForTool(
  tool: Pick<ToolChip, "tool" | "status" | "action" | "displayText" | "data">,
): OutcomeReceiptModel {
  if (tool.status === "calling") {
    return { title: "正在处理", detail: "完成后会在这里说明结果。", tone: "loading" };
  }
  if (tool.status === "in_progress") {
    return {
      title: "操作仍在处理中",
      detail: safeDetail(tool.displayText, batchReceiptDetail(tool.data || {}) || "已有操作正在处理，没有重复执行。"),
      tone: "info",
    };
  }
  if (tool.status === "needs_clarification") {
    return { title: "需要你确认", detail: "请核对下面的内容后再继续。", tone: "pending" };
  }
  if (tool.status === "cancelled") {
    return {
      title: "操作已取消",
      detail: safeDetail(tool.displayText, batchReceiptDetail(tool.data || {}) || "本次没有继续执行后续操作。"),
      tone: "info",
    };
  }
  if (tool.status === "interrupted") {
    return {
      title: "操作意外中断",
      detail: safeDetail(tool.displayText, batchReceiptDetail(tool.data || {}) || "部分操作可能没有执行，请核对结果后重试。"),
      tone: "error",
    };
  }
  if (tool.status === "failed" || tool.status === "timeout") {
    return {
      title: "这次操作没有完成",
      detail: safeDetail(tool.displayText, batchReceiptDetail(tool.data || {}) || "没有产生变更，可以稍后重试或联系家人。"),
      tone: "error",
    };
  }

  const name = tool.tool.toLowerCase();
  const action = (tool.action || "").toLowerCase();
  const data = tool.data || {};

  if (name.includes("memory") || action.includes("memory") || action === "note") {
    const consent = String(data.consent_status || data.status || "").toLowerCase();
    if (action.includes("recall")) {
      const empty = ["empty", "unauthorized"].includes(consent);
      return {
        title: empty ? "没有找到可使用的长期记忆" : "已查看你同意保留的记忆",
        detail: safeDetail(
          tool.displayText,
          empty ? "没有用未获同意的内容补全回答。" : "只使用了仍在保留期内且已获同意的内容。",
        ),
        tone: "info",
      };
    }
    if (consent === "pending") {
      return {
        title: "这条记忆等待你的同意",
        detail: safeDetail(tool.displayText, "在你同意前，它不会用于长期陪伴。"),
        tone: "pending",
      };
    }
    if (consent === "deleted" || actionIncludes(action, ["delete", "remove"])) {
      return {
        title: "记忆已删除",
        detail: safeDetail(tool.displayText, "这条内容不再用于后续陪伴。"),
        tone: "success",
      };
    }
    if (consent === "refused") {
      return {
        title: "这条内容没有作为长期记忆保存",
        detail: safeDetail(tool.displayText, "原来的照护任务和升级规则没有因此改变。"),
        tone: "info",
      };
    }
    return {
      title: "记忆设置已更新",
      detail: safeDetail(tool.displayText, "已按你的选择更新。"),
      tone: "success",
    };
  }

  if (name.includes("caretask") || name.includes("reminder") || actionIncludes(action, ["task", "reminder"])) {
    if (action.includes("list")) {
      return {
        title: "已查看照护事项",
        detail: "只读取了当前任务，没有修改任何提醒。",
        tone: "info",
      };
    }
    if (action.includes("reuse") && !action.includes("updated")) {
      return {
        title: "已有相同的照护提醒",
        detail: safeDetail(tool.displayText, "没有重复建立新的提醒。"),
        tone: "info",
      };
    }
    if (action.includes("schedule_updated")) {
      return {
        title: "提醒时间已更新",
        detail: safeDetail(tool.displayText, "沿用了原来的照护事项，没有重复建立。"),
        tone: "success",
      };
    }
    if (actionIncludes(action, ["create", "add"])) {
      return {
        title: "照护提醒已建立",
        detail: safeDetail(tool.displayText, "提醒已经保存，可以在今日事项中查看。"),
        tone: "success",
      };
    }
    if (actionIncludes(action, ["complete", "done", "acknowledge"])) {
      return {
        title: "已记录完成",
        detail: safeDetail(tool.displayText, "这件事项已更新为完成。"),
        tone: "success",
      };
    }
    if (actionIncludes(action, ["snooze", "delay"])) {
      return {
        title: "提醒已延后",
        detail: safeDetail(tool.displayText, "新的提醒时间已经保存。"),
        tone: "success",
      };
    }
    if (actionIncludes(action, ["cancel"])) {
      return {
        title: "提醒已取消",
        detail: safeDetail(tool.displayText, "这项提醒不会再继续。"),
        tone: "success",
      };
    }
    if (actionIncludes(action, ["missed"])) {
      return {
        title: "已记录为错过",
        detail: safeDetail(tool.displayText, "可以在今日事项中继续标记完成或寻求帮助。"),
        tone: "pending",
      };
    }
    return {
      title: "照护事项已更新",
      detail: safeDetail(tool.displayText, "可以在今日事项中核对结果。"),
      tone: "success",
    };
  }

  if (name.includes("contact") || name.includes("notify") || actionIncludes(action, ["contact", "notify"])) {
    return {
      title: "联系请求已记录",
      detail: safeDetail(tool.displayText, "请以页面显示的送达状态为准。"),
      tone: "success",
    };
  }

  return {
    title: "操作已完成",
    detail: safeDetail(tool.displayText, "结果已经更新。"),
    tone: "success",
  };
}
