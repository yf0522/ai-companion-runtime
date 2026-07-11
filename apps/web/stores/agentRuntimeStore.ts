import { create } from "zustand";

/** Sole production runtime id (legacy `pi_experimental` wire value retained). */
export type AgentRuntimeId = "pi_experimental";

export const PI_ONLY_RUNTIME: AgentRuntimeId = "pi_experimental";

const STORAGE_KEY = "companion.agent_runtime";

/** Pi-only product — no selectable harness escape in UI. */
export const AGENT_RUNTIME_OPTIONS: {
  id: AgentRuntimeId;
  label: string;
  description: string;
}[] = [
  {
    id: "pi_experimental",
    label: "Pi",
    description: "生产路径：风险优先 + FC 工具 + mem0 记忆",
  },
];

function readStoredRuntime(): AgentRuntimeId {
  if (typeof window === "undefined") return PI_ONLY_RUNTIME;
  // Coerce any legacy preference (incl. harness) to Pi-only.
  localStorage.setItem(STORAGE_KEY, PI_ONLY_RUNTIME);
  return PI_ONLY_RUNTIME;
}

interface AgentRuntimeState {
  runtime: AgentRuntimeId;
  hydrated: boolean;
  setRuntime: (runtime: AgentRuntimeId) => void;
  hydrate: () => void;
}

/** Always Pi on SSR + client — no harness/runtime escape UI. */
export const useAgentRuntimeStore = create<AgentRuntimeState>((set) => ({
  runtime: PI_ONLY_RUNTIME,
  hydrated: false,
  hydrate: () => {
    set({ runtime: readStoredRuntime(), hydrated: true });
  },
  setRuntime: (_runtime) => {
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, PI_ONLY_RUNTIME);
    }
    set({ runtime: PI_ONLY_RUNTIME, hydrated: true });
  },
}));
