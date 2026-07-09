"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getAuthHeaders(): HeadersInit {
  try {
    const raw = localStorage.getItem("companion-auth");
    if (raw) {
      const parsed = JSON.parse(raw);
      const token = parsed?.state?.token;
      if (token) {
        return { Authorization: `Bearer ${token}` };
      }
    }
  } catch {
    // ignore
  }
  return {};
}

interface Notification {
  id: string;
  risk_level: string;
  risk_category: string;
  summary: string;
  webhook_status: string | null;
  created_at: string | null;
}

const riskBadgeStyles: Record<string, string> = {
  critical: "bg-red-100 text-red-700 border-red-200",
  high: "bg-orange-100 text-orange-700 border-orange-200",
  medium: "bg-yellow-100 text-yellow-700 border-yellow-200",
  low: "bg-green-100 text-green-700 border-green-200",
};

const riskLabels: Record<string, string> = {
  critical: "紧急",
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

const categoryLabels: Record<string, string> = {
  health_emergency: "健康紧急",
  scam: "诈骗风险",
  emotional: "情绪异常",
  suicide: "自伤风险",
  abuse: "受虐风险",
};

function formatTime(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${API_URL}/api/notifications`, {
          headers: getAuthHeaders(),
        });
        if (res.status === 401) {
          router.push("/login");
          return;
        }
        if (!res.ok) throw new Error("Failed to load notifications");
        const data = await res.json();
        setNotifications(data);
      } catch (e: any) {
        setError(e.message || "Failed to load");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [router]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-2xl px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <a href="/chat" className="text-sm text-indigo-500 hover:underline">
            &larr; 返回聊天
          </a>
          <h1 className="mt-2 text-2xl font-bold text-gray-800">风险通知</h1>
          <p className="mt-1 text-sm text-gray-500">
            系统检测到的风险事件记录
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent" />
          </div>
        )}

        {/* Empty state */}
        {!loading && notifications.length === 0 && !error && (
          <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-400">
            暂无风险通知
          </div>
        )}

        {/* Notification List */}
        {!loading && notifications.length > 0 && (
          <div className="space-y-3">
            {notifications.map((n) => (
              <div
                key={n.id}
                className="rounded-xl border border-gray-200 bg-white p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${
                        riskBadgeStyles[n.risk_level] ||
                        "bg-gray-100 text-gray-600 border-gray-200"
                      }`}
                    >
                      {riskLabels[n.risk_level] || n.risk_level}
                    </span>
                    <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] text-gray-500">
                      {categoryLabels[n.risk_category] || n.risk_category}
                    </span>
                  </div>
                  <span className="text-[11px] text-gray-400">
                    {formatTime(n.created_at)}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-gray-700">
                  {n.summary}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
