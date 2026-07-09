"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/authStore";

type Reminder = {
  id: string;
  label: string;
  timer_type: string;
  repeat_mode: string;
  duration_sec: number;
  hour: number | null;
  minute: number | null;
  created_at: string;
  status: string;
};

type NotificationItem = {
  id: string;
  category: string;
  title: string;
  message: string;
  severity: string;
  status: string;
  created_at: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const CATEGORY_META: Record<string, { label: string; tone: string }> = {
  scam_alert: { label: "诈骗预警", tone: "bg-red-100 text-red-700 border-red-200" },
  emotional_low: { label: "情绪关怀", tone: "bg-yellow-100 text-yellow-700 border-yellow-200" },
  health_emergency: { label: "健康紧急", tone: "bg-orange-100 text-orange-700 border-orange-200" },
};

function formatTime(value: string) {
  try {
    return new Date(value).toLocaleString("zh-CN");
  } catch {
    return value;
  }
}

export default function NotificationsPage() {
  const token = useAuthStore((state) => state.token);
  const clearAuth = useAuthStore((state) => state.clearAuth);
  const router = useRouter();
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      router.push("/login");
      return;
    }

    const headers = { Authorization: `Bearer ${token}` };

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [r1, r2] = await Promise.all([
          fetch(`${API_URL}/api/reminders`, { headers }),
          fetch(`${API_URL}/api/notifications`, { headers }),
        ]);

        if (!r1.ok || !r2.ok) {
          if (r1.status === 401 || r2.status === 401) {
            clearAuth();
            router.push("/login");
            return;
          }
          throw new Error("接口请求失败");
        }

        const reminderData = await r1.json();
        const notificationData = await r2.json();
        setReminders(reminderData.items || []);
        setNotifications(notificationData.items || []);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [token, clearAuth, router]);

  return (
    <div className="mx-auto min-h-screen max-w-4xl px-4 py-6">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-[28px] font-semibold text-gray-800">
            家属与提醒看板
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            风险分类页面与后端字段保持一致：scam_alert / emotional_low / health_emergency
          </p>
        </div>
        <Link href="/chat" className="text-sm text-indigo-500 hover:underline">
          返回聊天
        </Link>
      </div>

      {loading ? (
        <p className="text-sm text-gray-500">加载中...</p>
      ) : error ? (
        <p className="text-sm text-red-500">{error}</p>
      ) : null}

      <section className="mb-8 rounded-xl border bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold text-gray-700">提醒事件</h2>
        {reminders.length === 0 ? (
          <p className="text-sm text-gray-500">暂无提醒事件</p>
        ) : (
          <div className="space-y-2">
            {reminders.map((item) => (
              <div key={item.id} className="rounded-lg border p-3 text-sm">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-medium text-gray-700">{item.label}</span>
                  <span className="text-xs text-gray-400">{item.status}</span>
                </div>
                <div className="text-xs text-gray-500">
                  类型: {item.timer_type} · 重复: {item.repeat_mode} · 创建:
                  {formatTime(item.created_at)}
                </div>
                <div className="text-xs text-gray-500">
                  {item.hour != null && item.minute != null ? `时间: ${item.hour}:${String(item.minute).padStart(2, "0")} ` : ""}
                  {item.duration_sec > 0 ? `倒计时: ${item.duration_sec}s` : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl border bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold text-gray-700">家属通知</h2>
        {notifications.length === 0 ? (
          <p className="text-sm text-gray-500">暂无待处理通知</p>
        ) : (
          <div className="space-y-2">
            {notifications.map((item) => {
              const meta = CATEGORY_META[item.category] || {
                label: item.category || "告警",
                tone: "bg-gray-100 text-gray-700 border-gray-200",
              };
              return (
                <div key={item.id} className="rounded-lg border p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className={`rounded-full border px-2 py-0.5 text-xs ${meta.tone}`}>
                      {meta.label}
                    </span>
                    <span className="text-xs text-gray-400">{item.status}</span>
                  </div>
                  <div className="text-sm font-medium text-gray-700">{item.title}</div>
                  <p className="mt-1 text-sm text-gray-500">{item.message}</p>
                  <div className="mt-2 text-xs text-gray-400">
                    severity: {item.severity} · {formatTime(item.created_at)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
