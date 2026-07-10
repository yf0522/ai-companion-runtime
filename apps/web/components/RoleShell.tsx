"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import {
  Bell,
  Bot,
  CheckSquare,
  ClipboardCheck,
  HeartHandshake,
  HelpCircle,
  Home,
  LogOut,
  RadioTower,
  ShieldCheck,
  Users,
  Waypoints,
  type LucideIcon,
} from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import {
  defaultRouteForRole,
  navForRole,
  normalizeRole,
} from "@/lib/role-routes.mjs";

type ProductRole = "elder" | "family" | "operator";

const roleLabels: Record<ProductRole, string> = {
  elder: "长者",
  family: "家属",
  operator: "照护运营",
};

const roleDescriptions: Record<ProductRole, string> = {
  elder: "日常陪伴与照护确认",
  family: "家庭照护工作台",
  operator: "安全与服务运营",
};

const iconMap: Record<string, LucideIcon> = {
  "/elder/companion": HeartHandshake,
  "/elder/today": CheckSquare,
  "/elder/help": HelpCircle,
  "/family/overview": Home,
  "/family/tasks": ClipboardCheck,
  "/family/alerts": Bell,
  "/family/people": Users,
  "/family/contacts": Waypoints,
  "/family/readiness": ShieldCheck,
  "/family/summary": Bot,
  "/ops/care": ShieldCheck,
  "/ops/households/readiness": Home,
  "/ops/traces": RadioTower,
};

function Brand({ role }: { role: ProductRole }) {
  return (
    <Link href={defaultRouteForRole(role)} className="flex min-h-0 items-center gap-3">
      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#10201d] text-white">
        <HeartHandshake size={21} />
      </span>
      <span>
        <strong className="block text-base">Companion</strong>
        <span className="text-xs text-muted">{roleDescriptions[role]}</span>
      </span>
    </Link>
  );
}

export default function RoleShell({
  role,
  title,
  subtitle,
  children,
}: {
  role: ProductRole;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const token = useAuthStore((state) => state.token);
  const hydrated = useAuthStore((state) => state.hydrated);
  const setHydrated = useAuthStore((state) => state.setHydrated);
  const authRole = useAuthStore((state) => state.role);
  const username = useAuthStore((state) => state.username);
  const clearAuth = useAuthStore((state) => state.clearAuth);
  const normalizedAuthRole = normalizeRole(authRole);
  const nav = useMemo(() => navForRole(role), [role]);
  const roleMismatch = Boolean(token && normalizedAuthRole !== role);

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated();
      return;
    }
    void Promise.resolve(useAuthStore.persist.rehydrate()).finally(setHydrated);
  }, [setHydrated]);

  useEffect(() => {
    if (hydrated && !token) router.push("/login");
  }, [hydrated, router, token]);

  const logout = () => {
    clearAuth();
    router.push("/login");
  };

  if (!hydrated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas text-base text-muted">
        正在恢复照护空间
      </div>
    );
  }

  return (
    <div className={`min-h-screen bg-canvas text-ink md:grid ${role === "elder" ? "md:grid-cols-[232px_1fr]" : "md:grid-cols-[256px_1fr]"}`}>
      <aside className="hidden min-h-screen border-r border-border bg-surface md:sticky md:top-0 md:flex md:h-screen md:flex-col">
        <div className="border-b border-border px-5 py-5">
          <Brand role={role} />
        </div>

        <nav aria-label={`${roleLabels[role]}导航`} className="flex-1 space-y-1 overflow-y-auto p-3">
          {nav.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = iconMap[item.href] || Home;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-12 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold transition ${active ? "bg-primary-soft text-primary-strong" : "text-muted hover:bg-[#f1f5f3] hover:text-ink"}`}
              >
                <Icon size={19} strokeWidth={2} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-border p-3">
          <div className="mb-2 flex items-center gap-3 rounded-lg bg-[#f4f7f6] px-3 py-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#dce8e4] text-xs font-bold text-primary-strong">
              {(username || "U").slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0">
              <strong className="block truncate text-sm">{username || "未登录"}</strong>
              <span className="text-xs text-muted">{roleLabels[role]}</span>
            </span>
          </div>
          <button type="button" onClick={logout} className="btn-quiet w-full justify-start">
            <LogOut size={17} />
            退出登录
          </button>
        </div>
      </aside>

      <div className="min-w-0 pb-24 md:pb-0">
        <header className="border-b border-border bg-surface/95 px-4 py-4 backdrop-blur sm:px-6 lg:px-8">
          <div className="mx-auto flex max-w-[1320px] items-start justify-between gap-4">
            <div>
              <div className="eyebrow">{roleDescriptions[role]}</div>
              <h1 className={`${role === "elder" ? "text-[30px]" : "text-2xl"} mt-1 font-bold leading-tight text-ink`}>
                {title}
              </h1>
              {subtitle && <p className="mt-1 max-w-3xl text-base leading-7 text-muted">{subtitle}</p>}
            </div>
            <div className="flex h-10 items-center rounded-full border border-border bg-[#f7faf8] px-3 text-sm font-semibold text-muted md:hidden">
              {roleLabels[role]}
            </div>
          </div>
        </header>

        <main className={`mx-auto max-w-[1320px] px-4 py-5 sm:px-6 lg:px-8 ${role === "elder" ? "text-[18px]" : ""}`}>
          {roleMismatch && (
            <div role="alert" className="mb-5 rounded-lg border border-status-warning bg-status-warning-soft p-4 text-base">
              <strong>当前账号属于{roleLabels[normalizedAuthRole]}</strong>
              <p className="mt-1 text-sm">界面不会改变服务端权限。请返回对应工作区继续。</p>
              <button type="button" className="btn-secondary mt-3" onClick={() => router.push(defaultRouteForRole(authRole))}>
                回到我的首页
              </button>
            </div>
          )}
          {children}
        </main>
      </div>

      <nav aria-label={`${roleLabels[role]}移动导航`} className="fixed inset-x-0 bottom-0 z-40 flex gap-1 overflow-x-auto border-t border-border bg-surface/95 px-2 pb-[max(.5rem,env(safe-area-inset-bottom))] pt-2 shadow-[0_-8px_24px_rgb(20_42_35_/_8%)] backdrop-blur md:hidden">
        {nav.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = iconMap[item.href] || Home;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-h-[54px] min-w-[72px] flex-1 flex-col items-center justify-center gap-1 rounded-lg px-1 text-[11px] font-semibold ${active ? "bg-primary-soft text-primary-strong" : "text-muted"}`}
            >
              <Icon size={19} />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
