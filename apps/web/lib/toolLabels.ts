/** Map wire tool names to elder-facing chip copy (Pi 3-tool whitelist). */

export type ToolFamily = "memory" | "caretask" | "utility";

export interface ToolChipCopy {
  /** Wire / product family id shown on the chip badge. */
  family: ToolFamily;
  /** Short Chinese label for the chip name. */
  name: string;
  /** Default action target when the backend omits `action`. */
  defaultTarget: string;
}

const LEGACY_TO_FAMILY: Record<string, ToolFamily> = {
  memory: "memory",
  caretask: "caretask",
  utility: "utility",
  reminder: "caretask",
  weather: "utility",
  calculator: "utility",
  search: "utility",
};

const FAMILY_COPY: Record<ToolFamily, ToolChipCopy> = {
  memory: {
    family: "memory",
    name: "记忆 memory",
    defaultTarget: "记下或召回",
  },
  caretask: {
    family: "caretask",
    name: "照护任务 caretask",
    defaultTarget: "列表或创建",
  },
  utility: {
    family: "utility",
    name: "实用工具 utility",
    defaultTarget: "查询或计算",
  },
};

export function resolveToolFamily(tool: string): ToolFamily | null {
  const key = tool.trim().toLowerCase();
  return LEGACY_TO_FAMILY[key] ?? null;
}

export function toolChipCopy(tool: string): ToolChipCopy {
  const family = resolveToolFamily(tool);
  if (family) return FAMILY_COPY[family];
  return {
    family: "utility",
    name: tool.trim() || "工具",
    defaultTarget: "照护动作",
  };
}

export function toolChipTarget(tool: string, action?: string, status?: string): string {
  if (action && action.trim()) return action.trim();
  if (status === "needs_clarification") return "等待确认";
  return toolChipCopy(tool).defaultTarget;
}

/** Group header above tool chips — names the families in play, not a generic 照护动作. */
export function toolGroupLabel(tools: string[]): string {
  const families: ToolFamily[] = [];
  for (const tool of tools) {
    const family = resolveToolFamily(tool) ?? "utility";
    if (!families.includes(family)) families.push(family);
  }
  if (families.length === 0) return "正在使用工具";
  if (families.length === 1) {
    const copy = FAMILY_COPY[families[0]];
    return `正在使用${copy.name}`;
  }
  return `正在使用：${families.map((f) => FAMILY_COPY[f].name).join("、")}`;
}
