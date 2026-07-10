"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { TextInput } from "@astryxdesign/core/TextInput";
import { LockKeyhole, UserRound } from "lucide-react";
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

  async function handleSubmit(event: React.FormEvent) {
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
  }

  return (
    <main className="auth-screen">
      <header className="auth-header">
        <a href="/" className="consumer-wordmark">Companion</a>
        <span>安心照护，清楚回应</span>
      </header>
      <div className="auth-shell">
        <section className="auth-story">
          <p className="auth-story-context">陪伴与家庭照护</p>
          <h1>让每一件需要关心的事，都有清楚的下一步。</h1>
          <p className="auth-story-copy">Companion 帮助长者完成日常事项，也让家人只在真正需要时收到清楚、可行动的提醒。</p>
          <ul className="auth-trust-list">
            <li><strong>先看当下</strong><span>需要处理的情况永远排在最前面。</span></li>
            <li><strong>尊重隐私</strong><span>家人看到照护结果，不默认看到私人对话。</span></li>
            <li><strong>有人负责</strong><span>重要事项会说明是否送达、由谁跟进。</span></li>
          </ul>
          <p className="auth-safety-note">遇到立即危险时，请直接联系家人和本地紧急服务。</p>
        </section>

        <section className="auth-form-plane">
          <form className="auth-form" onSubmit={handleSubmit}>
            <p className="auth-form-context">{isRegister ? "创建照护账号" : "欢迎回来"}</p>
            <Heading level={1}>{isRegister ? "创建照护账号" : "进入照护空间"}</Heading>
            <p className="auth-form-copy">{isRegister ? "选择你的使用身份，进入对应的照护空间。" : "继续查看今天的陪伴、照护任务和家庭提醒。"}</p>

            <div className="auth-fields">
              <TextInput label="用户名" value={username} onChange={setUsername} width="100%" hasAutoFocus startIcon={<Icon icon={UserRound} size="sm" />} />
              <TextInput label="密码" type="password" value={password} onChange={setPassword} width="100%" startIcon={<Icon icon={LockKeyhole} size="sm" />} status={error ? { type: "error", message: error } : undefined} />

              {isRegister && (
                <div>
                  <p className="auth-field-label">使用身份</p>
                  <SegmentedControl value={role} onChange={(value) => setRole(value as "elder" | "family")} label="使用身份" layout="fill" size="md">
                    <SegmentedControlItem value="elder" label="长者本人" />
                    <SegmentedControlItem value="family" label="家属照护" />
                  </SegmentedControl>
                </div>
              )}
            </div>

            <div className="auth-actions">
              <Button type="submit" label={isRegister ? "创建并进入" : "安全登录"} variant="primary" size="lg" isLoading={loading} isDisabled={!username.trim() || !password.trim()} />
              <Button type="button" label={isRegister ? "已有账号，返回登录" : "创建新账号"} variant="ghost" size="lg" onClick={() => { setIsRegister((value) => !value); setError(null); }} />
            </div>
            <p className="auth-privacy-copy">你的权限由服务端验证，界面只显示已授权的照护信息。</p>
          </form>
        </section>
      </div>
    </main>
  );
}
