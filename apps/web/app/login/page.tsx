"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/authStore";
import { defaultRouteForRole } from "@/lib/role-routes.mjs";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [role, setRole] = useState<"elder" | "family">("elder");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { login, register } = useAuthStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setError(null);
    setLoading(true);
    try {
      if (isRegister) {
        await register(username.trim(), password, role);
      } else {
        await login(username.trim(), password);
      }
      router.push(defaultRouteForRole(useAuthStore.getState().role));
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-8">
      <main className="w-full max-w-md rounded-md border border-border bg-surface p-6 sm:p-8">
        <div className="mb-6 flex flex-col items-center">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-md bg-primary text-xl font-bold text-white">
            C
          </div>
          <h1 className="text-2xl font-semibold text-ink">
            {isRegister ? "创建账号" : "登录智慧陪伴"}
          </h1>
          <p className="mt-2 text-center text-base leading-7 text-muted">
            {isRegister ? "选择使用身份，进入对应的照护界面。" : "登录后继续处理陪伴、提醒和照护事项。"}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="mb-2 block text-base font-medium text-ink">
              用户名
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="min-h-11 w-full rounded-md border border-border bg-surface px-4 py-3 text-base text-ink"
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-2 block text-base font-medium text-ink">
              密码
            </label>
            <input
              id="password"
              type="password"
              autoComplete={isRegister ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="min-h-11 w-full rounded-md border border-border bg-surface px-4 py-3 text-base text-ink"
            />
          </div>

          {isRegister && (
            <fieldset>
              <legend className="mb-2 text-base font-medium text-ink">使用身份</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                {[
                  { value: "elder", label: "长者本人", description: "陪伴和今日事项" },
                  { value: "family", label: "家属", description: "任务和告警管理" },
                ].map((option) => (
                  <label
                    key={option.value}
                    className={`min-h-11 cursor-pointer rounded-md border p-3 ${
                      role === option.value ? "border-primary bg-primary-soft" : "border-border"
                    }`}
                  >
                    <input
                      type="radio"
                      name="role"
                      value={option.value}
                      checked={role === option.value}
                      onChange={() => setRole(option.value as "elder" | "family")}
                      className="mr-2"
                    />
                    <span className="font-medium text-ink">{option.label}</span>
                    <span className="mt-1 block pl-6 text-sm text-muted">{option.description}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          {error && (
            <p role="alert" className="rounded-md border border-status-critical bg-status-critical-soft px-3 py-2 text-base text-ink">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || !username.trim() || !password.trim()}
            className="btn-primary w-full"
          >
            {loading ? "处理中" : isRegister ? "创建账号" : "登录"}
          </button>
        </form>

        <div className="mt-4 text-center">
          <button
            onClick={() => {
              setIsRegister(!isRegister);
              setError(null);
            }}
            type="button"
            className="btn-secondary w-full"
          >
            {isRegister
              ? "已有账号，返回登录"
              : "没有账号，创建一个"}
          </button>
        </div>
      </main>
    </div>
  );
}
