"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Activity, LockKeyhole, Radar, ShieldCheck, UserRound } from "lucide-react";
import SignalField from "@/components/SignalField";
import { useAuthStore } from "@/stores/authStore";
import { defaultRouteForRole } from "@/lib/role-routes.mjs";

function BrandMark() {
  return <span className="brand-mark"><span className="brand-mark-core"><span /><span /><span /><span /></span></span>;
}

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
      <SignalField />
      <div className="auth-grid">
        <section className="auth-story">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <BrandMark />
            <div>
              <Text display="block" weight="semibold" style={{ color: "#f4fffc" }}>Companion</Text>
              <Text display="block" type="supporting" style={{ color: "#8ea49f" }}>Ambient care runtime</Text>
            </div>
          </div>

          <div className="auth-story-copy">
            <Badge label="REAL-TIME CARE INTELLIGENCE" variant="teal" />
            <h1>AI 在这里，不只是回答。</h1>
            <p>它持续理解、执行照护任务、拦截风险、追踪投递，并在需要时把责任交给具体的人。</p>
          </div>

          <div className="auth-proof" aria-label="产品运行能力">
            <div><Icon icon={Activity} color="cyan" /><Text display="block" weight="semibold" style={{ marginTop: 16, color: "#f4fffc" }}>实时陪伴</Text><Text display="block" type="supporting" style={{ marginTop: 6, color: "#8ea49f" }}>WebSocket 流式响应与运行状态</Text></div>
            <div><Icon icon={Radar} color="orange" /><Text display="block" weight="semibold" style={{ marginTop: 16, color: "#f4fffc" }}>风险优先</Text><Text display="block" type="supporting" style={{ marginTop: 6, color: "#8ea49f" }}>诈骗、情绪和安全策略先于生成</Text></div>
            <div><Icon icon={ShieldCheck} color="green" /><Text display="block" weight="semibold" style={{ marginTop: 16, color: "#f4fffc" }}>结果可追踪</Text><Text display="block" type="supporting" style={{ marginTop: 6, color: "#8ea49f" }}>任务、回执、人工处置与 Trace</Text></div>
          </div>
        </section>

        <section className="auth-form-plane">
          <form className="auth-form" onSubmit={handleSubmit}>
            <Badge label={isRegister ? "CREATE CARE SPACE" : "SECURE ACCESS"} variant="neutral" />
            <Heading level={1}>{isRegister ? "创建照护账号" : "进入照护空间"}</Heading>
            <p className="auth-form-copy">{isRegister ? "选择真实使用身份。权限由服务端控制，界面只呈现对应工作流。" : "继续处理陪伴、照护任务、告警和人工协同。"}</p>

            <div className="auth-fields">
              <TextInput label="用户名" value={username} onChange={setUsername} width="100%" hasAutoFocus startIcon={<Icon icon={UserRound} size="sm" />} />
              <TextInput label="密码" type="password" value={password} onChange={setPassword} width="100%" startIcon={<Icon icon={LockKeyhole} size="sm" />} status={error ? { type: "error", message: error } : undefined} />

              {isRegister && (
                <div>
                  <Text display="block" type="label" style={{ marginBottom: 8 }}>使用身份</Text>
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
          </form>
        </section>
      </div>
    </main>
  );
}
