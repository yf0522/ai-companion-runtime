"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { defaultRouteForRole } from "@/lib/role-routes.mjs";
import { useAuthStore } from "@/stores/authStore";

export default function Home() {
  const router = useRouter();
  const token = useAuthStore((state) => state.token);
  const role = useAuthStore((state) => state.role);

  useEffect(() => {
    router.replace(token ? defaultRouteForRole(role) : "/login");
  }, [role, router, token]);

  return (
    <main className="min-h-screen bg-canvas p-6 text-ink" aria-live="polite">
      正在进入对应角色首页...
    </main>
  );
}
