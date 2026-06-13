import { create } from "zustand";
import { persist } from "zustand/middleware";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface AuthState {
  token: string | null;
  userId: string | null;
  username: string | null;

  setAuth: (token: string, userId: string, username: string) => void;
  clearAuth: () => void;
  isAuthenticated: () => boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      userId: null,
      username: null,

      setAuth: (token, userId, username) => set({ token, userId, username }),
      clearAuth: () => set({ token: null, userId: null, username: null }),
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
        });
      },

      register: async (username: string, password: string) => {
        const res = await fetch(`${API_URL}/api/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
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
        });
      },
    }),
    {
      name: "companion-auth",
      partialize: (state) => ({
        token: state.token,
        userId: state.userId,
        username: state.username,
      }),
    }
  )
);
