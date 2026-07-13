"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { SideNav, SideNavHeading, SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { Text } from "@astryxdesign/core/Text";
import {
  Bell,
  Bot,
  CheckSquare,
  ChevronDown,
  ClipboardCheck,
  HeartHandshake,
  HelpCircle,
  Home,
  Gauge,
  LogOut,
  Menu,
  RadioTower,
  ShieldCheck,
  Users,
  Waypoints,
  type LucideIcon,
} from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import { defaultRouteForRole, navForRole, normalizeRole } from "@/lib/role-routes.mjs";

type ProductRole = "elder" | "family" | "operator";
type NavItem = { href: string; label: string };

const roleLabels: Record<ProductRole, string> = {
  elder: "长者空间",
  family: "家庭照护",
  operator: "照护运营",
};

const roleDescriptions: Record<ProductRole, string> = {
  elder: "陪伴、确认与求助",
  family: "家庭照护与异常协同",
  operator: "处置、证据与运行状态",
};

const mobileNavLabels: Record<ProductRole, string> = {
  elder: "长者移动导航",
  family: "家属移动导航",
  operator: "照护运营移动导航",
};

const consumerPrimaryPaths: Record<"elder" | "family", string[]> = {
  elder: ["/elder/companion", "/elder/today", "/elder/help"],
  family: ["/family/overview", "/family/tasks", "/family/alerts", "/family/people"],
};

const consumerMobileLabels: Record<string, string> = {
  "/elder/companion": "陪伴",
  "/elder/today": "今日事项",
  "/elder/help": "帮助",
  "/family/overview": "概览",
  "/family/tasks": "任务",
  "/family/alerts": "告警",
  "/family/people": "家人",
};

const iconMap: Record<string, LucideIcon> = {
  "/elder/companion": HeartHandshake,
  "/elder/today": CheckSquare,
  "/elder/help": HelpCircle,
  "/elder/memory": ShieldCheck,
  "/family/overview": Home,
  "/family/tasks": ClipboardCheck,
  "/family/alerts": Bell,
  "/family/people": Users,
  "/family/contacts": Waypoints,
  "/family/readiness": ShieldCheck,
  "/family/summary": Bot,
  "/ops/care": ShieldCheck,
  "/ops/platform": Gauge,
  "/ops/households/readiness": Home,
  "/ops/traces": RadioTower,
};

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function RoleMismatch({
  normalizedAuthRole,
  onReturn,
}: {
  normalizedAuthRole: ProductRole;
  onReturn: () => void;
}) {
  return (
    <div className="role-mismatch" role="alert">
      <Text display="block" weight="semibold">当前账号属于{roleLabels[normalizedAuthRole]}</Text>
      <Text display="block" type="supporting">当前页面不会改变服务端权限，请返回你的工作区。</Text>
      <div style={{ marginTop: 12 }}>
        <Button label="回到我的首页" variant="secondary" onClick={onReturn} />
      </div>
    </div>
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
  const nav = useMemo(() => navForRole(role) as NavItem[], [role]);
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

  const logout = () => {
    clearAuth();
    router.push("/login");
  };
  const returnToRole = () => router.push(defaultRouteForRole(authRole));

  if (role !== "operator") {
    const primaryPaths = consumerPrimaryPaths[role];
    const primaryNav = nav.filter((item) => primaryPaths.includes(item.href));
    const secondaryNav = nav.filter((item) => !primaryPaths.includes(item.href));

    return (
      <div className="product-shell consumer-shell" data-role={role}>
        <header className="consumer-header">
          <div className="consumer-header-inner">
            <a href={defaultRouteForRole(role)} className="consumer-wordmark" aria-label="Companion 首页">Companion</a>

            <nav className="consumer-desktop-nav" aria-label={`${roleLabels[role]}主导航`}>
              {primaryNav.map((item) => (
                <a key={item.href} href={item.href} data-active={isActive(pathname, item.href) ? "true" : "false"}>
                  {item.label}
                </a>
              ))}
            </nav>

            <div className="consumer-header-actions">
              {secondaryNav.length > 0 && (
                <details className="consumer-menu">
                  <summary aria-label="打开全部功能">
                    <span className="consumer-menu-label">更多</span>
                    <Menu className="consumer-menu-icon" size={20} aria-hidden="true" />
                    <ChevronDown className="consumer-menu-chevron" size={16} aria-hidden="true" />
                  </summary>
                  <div className="consumer-menu-panel">
                    <p>全部功能</p>
                    {nav.map((item) => {
                      const NavIcon = iconMap[item.href] || Home;
                      return (
                        <a key={item.href} href={item.href} data-active={isActive(pathname, item.href) ? "true" : "false"}>
                          <NavIcon size={18} aria-hidden="true" />
                          <span>{item.label}</span>
                        </a>
                      );
                    })}
                  </div>
                </details>
              )}

              <details className="consumer-account">
                <summary aria-label="打开账号菜单">
                  <Avatar name={username || roleLabels[role]} size="small" />
                </summary>
                <div className="consumer-account-panel">
                  <strong>{username || roleLabels[role]}</strong>
                  <span>{roleLabels[role]}</span>
                  <button type="button" onClick={logout}><LogOut size={17} />退出登录</button>
                </div>
              </details>
            </div>
          </div>
        </header>

        {roleMismatch && <RoleMismatch normalizedAuthRole={normalizedAuthRole} onReturn={returnToRole} />}

        <main
          className="product-content consumer-content"
          data-role={role}
          data-companion={isCompanion ? "true" : "false"}
          aria-label={title}
        >
          <div className="sr-only">
            <h1>{title}</h1>
          </div>
          {children}
        </main>

        <nav aria-label={mobileNavLabels[role]} className="mobile-role-nav">
          {primaryNav.map((item) => {
            const NavIcon = iconMap[item.href] || Home;
            return (
              <a key={item.href} href={item.href} className="mobile-role-link" data-active={isActive(pathname, item.href) ? "true" : "false"}>
                <NavIcon size={19} aria-hidden="true" />
                <span>{consumerMobileLabels[item.href] || item.label}</span>
              </a>
            );
          })}
        </nav>
      </div>
    );
  }

  const sideNav = (
    <SideNav
      header={
        <SideNavHeading
          heading="Companion"
          subheading={roleDescriptions.operator}
          headingHref={defaultRouteForRole(role)}
        />
      }
      footer={
        <div className="operator-account">
          <div>
            <Avatar name={username || roleLabels.operator} size="small" />
            <div>
              <Text display="block" weight="semibold" maxLines={1}>{username || "未登录"}</Text>
              <Text display="block" type="supporting" color="secondary">{roleLabels.operator}</Text>
            </div>
          </div>
          <Button label="退出登录" variant="ghost" size="md" icon={<Icon icon={LogOut} size="sm" />} onClick={logout} />
        </div>
      }
      collapsible={{ defaultIsCollapsed: false, buttonLabel: "收起导航" }}
    >
      <SideNavSection title="运营工作区">
        {nav.map((item) => {
          const NavIcon = iconMap[item.href] || Home;
          return (
            <SideNavItem
              key={item.href}
              label={item.label}
              href={item.href}
              icon={<Icon icon={NavIcon} size="sm" />}
              isSelected={isActive(pathname, item.href)}
            />
          );
        })}
      </SideNavSection>
    </SideNav>
  );

  return (
    <div className="product-shell operator-shell">
      <AppShell sideNav={sideNav} mobileNav={{ breakpoint: "md" }} contentPadding={0} height="fill" variant="section">
        <div className="product-shell-main" data-role="operator">
          <header className="operator-topbar">
            <div>
              <h1>{title}</h1>
              {subtitle && <p>{subtitle}</p>}
            </div>
            <span>运营工作区</span>
          </header>

          {roleMismatch && <RoleMismatch normalizedAuthRole={normalizedAuthRole} onReturn={returnToRole} />}
          <main className="product-content operator-content" aria-label={title}>{children}</main>
        </div>
      </AppShell>
    </div>
  );
}
