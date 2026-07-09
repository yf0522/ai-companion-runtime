"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import { useAuthStore } from "@/stores/authStore";
import { defaultRouteForRole, navForRole, normalizeRole } from "@/lib/role-routes.mjs";

type ProductRole = "elder" | "family" | "operator";

const roleLabels: Record<ProductRole, string> = {
  elder: "长者",
  family: "家属",
  operator: "照护运营",
};

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

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated();
      return;
    }
    void Promise.resolve(useAuthStore.persist.rehydrate()).finally(setHydrated);
  }, [setHydrated]);

  useEffect(() => {
    if (hydrated && !token) {
      router.push("/login");
    }
  }, [hydrated, router, token]);

  const nav = useMemo(() => navForRole(role), [role]);
  const roleMismatch = token && normalizedAuthRole !== role;

  if (!hydrated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4 text-base text-muted">
        正在恢复登录状态
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-sm font-medium text-muted">
              智慧陪伴 · {roleLabels[role]}
            </div>
            <h1 className="mt-1 text-2xl font-semibold tracking-normal text-ink">
              {title}
            </h1>
            {subtitle && (
              <p className="mt-1 max-w-3xl text-base leading-7 text-muted">
                {subtitle}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <span className="rounded-md border border-border bg-canvas px-3 py-2">
              {username || "未登录"}
            </span>
            <button
              type="button"
              onClick={() => {
                clearAuth();
                router.push("/login");
              }}
              className="btn-secondary"
            >
              退出
            </button>
          </div>
        </div>
        <nav
          aria-label={`${roleLabels[role]}导航`}
          className="mx-auto flex max-w-6xl gap-2 overflow-x-auto px-4 pb-3 sm:px-6"
        >
          {nav.map((item) => {
            const active =
              pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`min-h-11 whitespace-nowrap rounded-md border px-4 py-3 text-base font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-focus ${
                  active
                    ? "border-primary bg-primary-soft text-primary-strong"
                    : "border-border bg-surface text-ink hover:bg-canvas"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        {roleMismatch && (
          <div
            role="alert"
            className="mb-5 rounded-md border border-status-warning bg-status-warning-soft p-4 text-base text-ink"
          >
            当前登录角色是{roleLabels[normalizedAuthRole]}。这里只做界面分流，权限仍由服务端接口决定。
            <button
              type="button"
              className="ml-0 mt-3 block min-h-11 rounded-md border border-status-warning px-4 py-2 font-medium sm:ml-3 sm:mt-0 sm:inline-block"
              onClick={() => router.push(defaultRouteForRole(authRole))}
            >
              回到我的首页
            </button>
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
