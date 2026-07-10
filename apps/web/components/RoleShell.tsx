"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { SideNav, SideNavHeading, SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { Text } from "@astryxdesign/core/Text";
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
import { defaultRouteForRole, navForRole, normalizeRole } from "@/lib/role-routes.mjs";

type ProductRole = "elder" | "family" | "operator";

const roleLabels: Record<ProductRole, string> = {
  elder: "长者空间",
  family: "家庭照护",
  operator: "照护运营",
};

const roleDescriptions: Record<ProductRole, string> = {
  elder: "陪伴、确认与求助",
  family: "异常优先的家庭协同",
  operator: "处置、证据与运行状态",
};

const mobileNavLabels: Record<ProductRole, string> = {
  elder: "长者移动导航",
  family: "家属移动导航",
  operator: "照护运营移动导航",
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

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <span className="brand-mark-core"><span /><span /><span /><span /></span>
    </span>
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
  const normalizedAuthRole = normalizeRole(authRole) as ProductRole;
  const nav = useMemo(() => navForRole(role), [role]);
  const roleMismatch = Boolean(token && normalizedAuthRole !== role);
  const isCompanion = pathname === "/elder/companion";

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

  if (!hydrated) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted">正在恢复照护空间</div>;
  }

  const sideNav = (
    <SideNav
      header={
        <SideNavHeading
          icon={<BrandMark />}
          heading="Companion"
          subheading={roleDescriptions[role]}
          headingHref={defaultRouteForRole(role)}
          headerEndContent={<Badge label="Live" variant="teal" />}
        />
      }
      footer={
        <div style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Avatar name={username || roleLabels[role]} size="small" />
            <div style={{ minWidth: 0 }}>
              <Text display="block" weight="semibold" maxLines={1}>{username || "未登录"}</Text>
              <Text display="block" type="supporting" color="secondary">{roleLabels[role]}</Text>
            </div>
          </div>
          <Button
            label="退出登录"
            variant="ghost"
            size="md"
            icon={<Icon icon={LogOut} size="sm" />}
            onClick={() => {
              clearAuth();
              router.push("/login");
            }}
          />
        </div>
      }
      collapsible={{ defaultIsCollapsed: false, buttonLabel: "收起导航" }}
    >
      <SideNavSection title={roleLabels[role]} subtitle={roleDescriptions[role]}>
        {nav.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const NavIcon = iconMap[item.href] || Home;
          return (
            <SideNavItem
              key={item.href}
              label={item.label}
              href={item.href}
              icon={<Icon icon={NavIcon} size="sm" />}
              isSelected={active}
            />
          );
        })}
      </SideNavSection>
    </SideNav>
  );

  return (
    <div className="product-shell">
      <AppShell
        sideNav={sideNav}
        mobileNav={{ breakpoint: "md" }}
        contentPadding={0}
        height="fill"
        variant="section"
      >
        <div className="product-shell-main" data-role={role}>
          <header className="product-topbar">
            <div className="product-topbar-copy">
              <h1 className="product-topbar-title">{title}</h1>
              {subtitle && <p className="product-topbar-subtitle">{subtitle}</p>}
            </div>
            <div className="product-topbar-meta">
              <Badge label={roleLabels[role]} variant={role === "operator" ? "orange" : "teal"} />
              <Badge label="权限隔离" variant="neutral" />
            </div>
          </header>

          {roleMismatch && (
            <div className="role-mismatch" role="alert">
              <Text display="block" weight="semibold">当前账号属于{roleLabels[normalizedAuthRole]}</Text>
              <Text display="block" type="supporting">界面不会改变服务端权限，请返回你的工作区。</Text>
              <div style={{ marginTop: 10 }}>
                <Button label="回到我的首页" variant="secondary" onClick={() => router.push(defaultRouteForRole(authRole))} />
              </div>
            </div>
          )}

          <main className="product-content" data-companion={isCompanion ? "true" : "false"}>{children}</main>
        </div>
      </AppShell>

      <nav aria-label={mobileNavLabels[role]} className="mobile-role-nav">
        {nav.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const NavIcon = iconMap[item.href] || Home;
          return (
            <a key={item.href} href={item.href} className="mobile-role-link" data-active={active ? "true" : "false"}>
              <NavIcon size={18} />
              <span>{item.label}</span>
            </a>
          );
        })}
      </nav>
    </div>
  );
}
