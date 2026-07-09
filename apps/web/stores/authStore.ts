import { create } from "zustand";
import { persist } from "zustand/middleware";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function parseJwtRole(token: string): string {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.role || "elder";
  } catch {
    return "elder";
  }
}

interface AuthState {
  token: string | null;
  userId: string | null;
  username: string | null;
  role: string | null;

  setAuth: (token: string, userId: string, username: string, role: string) => void;
  clearAuth: () => void;
  isAuthenticated: () => boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, role?: string) => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      userId: null,
      username: null,
      role: null,

      setAuth: (token, userId, username, role) => set({ token, userId, username, role }),
      clearAuth: () => set({ token: null, userId: null, username: null, role: null }),
      isAuthenticated: () => !!get().token,

      login: async (username: string, password: string) => {
        const res = await fetch(`${API_URL}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Login failed");
        }
        const data = await res.json();
        set({
          token: data.access_token,
          userId: data.user_id,
          username: data.username,
          role: parseJwtRole(data.access_token),
        });
      },

      register: async (username: string, password: string, role?: string) => {
        const res = await fetch(`${API_URL}/api/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password, ...(role ? { role } : {}) }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Registration failed");
        }
        const data = await res.json();
        set({
          token: data.access_token,
          userId: data.user_id,
          username: data.username,
          role: parseJwtRole(data.access_token),
        });
      },
    }),
    {
      name: "companion-auth",
      partialize: (state) => ({
        token: state.token,
        userId: state.userId,
        username: state.username,
        role: state.role,
      }),
    }
  )
);
