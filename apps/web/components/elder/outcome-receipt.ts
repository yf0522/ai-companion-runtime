import type { ToolChip } from "@/stores/chatStore";

export type OutcomeReceiptTone = "info" | "success" | "pending" | "error";

export interface OutcomeReceiptModel {
  title: string;
  detail: string;
  tone: OutcomeReceiptTone;
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

export function outcomeReceiptForTool(
  tool: Pick<ToolChip, "tool" | "status" | "action" | "displayText" | "data">,
): OutcomeReceiptModel {
  if (tool.status === "calling") {
    return { title: "正在处理", detail: "完成后会在这里说明结果。", tone: "info" };
  }
  if (tool.status === "needs_clarification") {
    return { title: "需要你确认", detail: "请核对下面的内容后再继续。", tone: "pending" };
  }
  if (tool.status === "failed" || tool.status === "timeout") {
    return {
      title: "这次操作没有完成",
      detail: safeDetail(tool.displayText, "没有产生变更，可以稍后重试或联系家人。"),
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
        detail: safeDetail(tool.displayText, "没有因此修改任何提醒。"),
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
