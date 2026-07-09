import { create } from "zustand";

export type AgentRuntimeId = "harness" | "pi_experimental";

const STORAGE_KEY = "companion.agent_runtime";

export const AGENT_RUNTIME_OPTIONS: {
  id: AgentRuntimeId;
  label: string;
  description: string;
}[] = [
  {
    id: "harness",
    label: "标准 Harness",
    description: "生产默认路径：风险优先 + 工具 + 记忆",
  },
  {
    id: "pi_experimental",
    label: "Pi (实验)",
    description: "实验性 Pi Agent 运行时（需服务端启用）",
  },
];

function readStoredRuntime(): AgentRuntimeId {
  if (typeof window === "undefined") return "harness";
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === "pi_experimental" || raw === "pi") return "pi_experimental";
  return "harness";
}

interface AgentRuntimeState {
  runtime: AgentRuntimeId;
  hydrated: boolean;
  setRuntime: (runtime: AgentRuntimeId) => void;
  hydrate: () => void;
}

/** Default harness on SSR + first client paint to avoid select title hydration mismatch. */
export const useAgentRuntimeStore = create<AgentRuntimeState>((set) => ({
  runtime: "harness",
  hydrated: false,
  hydrate: () => {
    set({ runtime: readStoredRuntime(), hydrated: true });
  },
  setRuntime: (runtime) => {
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, runtime);
    }
    set({ runtime, hydrated: true });
  },
}));
