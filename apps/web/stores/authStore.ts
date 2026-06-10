import { create } from "zustand";

interface AuthState {
  token: string | null;
  userId: string | null;

  setAuth: (token: string, userId: string) => void;
  clearAuth: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  userId: null,

  setAuth: (token, userId) => set({ token, userId }),
  clearAuth: () => set({ token: null, userId: null }),
  isAuthenticated: () => !!get().token,
}));
