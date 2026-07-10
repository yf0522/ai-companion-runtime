"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { HeartHandshake, LockKeyhole, Radar, ShieldCheck } from "lucide-react";
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

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setError(null);
    setLoading(true);
    try {
      if (isRegister) await register(username.trim(), password, role);
      else await login(username.trim(), password);
      router.push(defaultRouteForRole(useAuthStore.getState().role));
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "登录暂时不可用，请稍后重试。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#10201d] px-4 py-6 sm:px-6 lg:px-8">
      <main className="mx-auto grid min-h-[calc(100vh-3rem)] max-w-6xl overflow-hidden rounded-lg border border-white/10 bg-surface shadow-[0_28px_80px_rgb(0_0_0_/_28%)] lg:grid-cols-[1.08fr_.92fr]">
        <section className="relative order-2 flex flex-col justify-between bg-[#10201d] p-6 text-white sm:p-8 lg:order-1 lg:p-12">
          <div>
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-white text-[#10201d]"><HeartHandshake size={23} /></span>
              <div><strong className="block text-lg">Companion</strong><span className="text-sm text-white/60">长期陪伴与安全守护运行时</span></div>
            </div>
            <div className="mt-10 max-w-xl lg:mt-24">
              <p className="text-sm font-semibold text-[#72d8cc]">CALM INTELLIGENCE</p>
              <h1 className="mt-3 text-[30px] font-bold leading-[1.18] sm:text-[40px] lg:text-[46px]">每一次提醒、风险和求助，都有清楚的下一步。</h1>
              <p className="mt-5 max-w-lg text-lg leading-8 text-white/70">面向长者、家属和照护运营的同一套生产工作流。AI 负责理解与执行，人始终保留确认权。</p>
            </div>
          </div>
          <div className="mt-8 grid gap-3 sm:grid-cols-3 lg:mt-12 lg:grid-cols-1 xl:grid-cols-3">
            {[
              { icon: Radar, label: "风险分级", text: "优先暂停危险操作" },
              { icon: ShieldCheck, label: "证据可追踪", text: "关键动作保留回执" },
              { icon: LockKeyhole, label: "角色隔离", text: "隐私与权限按角色呈现" },
            ].map(({ icon: Icon, label, text }) => (
              <div key={label} className="border-t border-white/15 pt-3">
                <Icon size={18} className="text-[#72d8cc]" />
                <strong className="mt-2 block text-sm">{label}</strong>
                <span className="mt-1 block text-sm leading-6 text-white/55">{text}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="order-1 flex items-center bg-[#f7faf8] p-5 sm:p-8 lg:order-2 lg:p-12">
          <div className="mx-auto w-full max-w-md">
            <div className="eyebrow">Secure access</div>
            <h2 className="mt-2 text-3xl font-bold text-ink">{isRegister ? "创建照护账号" : "进入照护空间"}</h2>
            <p className="mt-2 text-base leading-7 text-muted">{isRegister ? "选择使用身份，系统会进入对应的工作界面。" : "继续处理陪伴、任务、告警和人工协同。"}</p>

            <form onSubmit={handleSubmit} className="mt-8 space-y-5">
              <div>
                <label htmlFor="username" className="mb-2 block text-sm font-semibold text-ink">用户名</label>
                <input id="username" type="text" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} className="field-control" autoFocus />
              </div>
              <div>
                <label htmlFor="password" className="mb-2 block text-sm font-semibold text-ink">密码</label>
                <input id="password" type="password" autoComplete={isRegister ? "new-password" : "current-password"} value={password} onChange={(event) => setPassword(event.target.value)} className="field-control" />
              </div>

              {isRegister && (
                <fieldset>
                  <legend className="mb-2 text-sm font-semibold text-ink">使用身份</legend>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {[
                      { value: "elder", label: "长者本人", description: "陪伴与今日事项" },
                      { value: "family", label: "家属", description: "任务与告警管理" },
                    ].map((option) => (
                      <label key={option.value} className={`cursor-pointer rounded-md border p-3 ${role === option.value ? "border-primary bg-primary-soft" : "border-border bg-surface"}`}>
                        <input type="radio" name="role" value={option.value} checked={role === option.value} onChange={() => setRole(option.value as "elder" | "family")} className="mr-2" />
                        <span className="font-semibold text-ink">{option.label}</span>
                        <span className="mt-1 block pl-6 text-sm text-muted">{option.description}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}

              {error && <p role="alert" className="rounded-md border border-status-critical bg-status-critical-soft px-4 py-3 text-base text-ink">{error}</p>}

              <button type="submit" disabled={loading || !username.trim() || !password.trim()} className="btn-primary w-full">
                {loading ? "正在验证" : isRegister ? "创建并进入" : "安全登录"}
              </button>
            </form>

            <button
              type="button"
              onClick={() => { setIsRegister((value) => !value); setError(null); }}
              className="btn-quiet mt-4 w-full"
            >
              {isRegister ? "已有账号，返回登录" : "首次使用，创建账号"}
            </button>
            <p className="mt-6 border-t border-border pt-5 text-sm leading-6 text-muted">紧急情况请直接联系本地紧急服务。系统不会替代医生、急救人员或金融机构。</p>
          </div>
        </section>
      </main>
    </div>
  );
}
