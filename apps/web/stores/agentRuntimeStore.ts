import { create } from "zustand";

export type AgentRuntimeId = "harness" | "pi_experimental";

const STORAGE_KEY = "companion.agent_runtime";

function configuredRuntime(): AgentRuntimeId {
  return process.env.NEXT_PUBLIC_AGENT_RUNTIME === "pi_experimental"
    ? "pi_experimental"
    : "harness";
}

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
  if (typeof localStorage === "undefined") return configuredRuntime();
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === "pi_experimental" || raw === "pi") return "pi_experimental";
  if (raw === "harness") return "harness";
  return configuredRuntime();
}

interface AgentRuntimeState {
  runtime: AgentRuntimeId;
  hydrated: boolean;
  setRuntime: (runtime: AgentRuntimeId) => void;
  hydrate: () => void;
}

/** Use the configured default on SSR; hydrate device choice before opening a socket. */
export const useAgentRuntimeStore = create<AgentRuntimeState>((set) => ({
  runtime: configuredRuntime(),
  hydrated: false,
  hydrate: () => {
    set({ runtime: readStoredRuntime(), hydrated: true });
  },
  setRuntime: (runtime) => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(STORAGE_KEY, runtime);
    }
    set({ runtime, hydrated: true });
  },
}));

export function getActiveAgentRuntime(): AgentRuntimeId {
  const state = useAgentRuntimeStore.getState();
  if (!state.hydrated) state.hydrate();
  return useAgentRuntimeStore.getState().runtime;
}
