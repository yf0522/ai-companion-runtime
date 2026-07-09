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
        return {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        };
      }
    }
  } catch {
    // ignore
  }
  return { "Content-Type": "application/json" };
}

interface Reminder {
  id: string;
  title: string;
  description: string | null;
  schedule_type: string;
  time_of_day: string | null;
  next_fire_at: string | null;
  is_active: boolean;
  created_by: string | null;
  created_at: string | null;
}

export default function RemindersPage() {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // New reminder form
  const [title, setTitle] = useState("");
  const [timeOfDay, setTimeOfDay] = useState("08:00");
  const [scheduleType, setScheduleType] = useState("daily");
  const [creating, setCreating] = useState(false);

  const router = useRouter();

  async function loadReminders() {
    try {
      const res = await fetch(`${API_URL}/api/reminders`, {
        headers: getAuthHeaders(),
      });
      if (res.status === 401) {
        router.push("/login");
        return;
      }
      if (!res.ok) throw new Error("Failed to load reminders");
      const data = await res.json();
      setReminders(data);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadReminders();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    try {
      const res = await fetch(`${API_URL}/api/reminders`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          title: title.trim(),
          time_of_day: timeOfDay,
          schedule_type: scheduleType,
        }),
      });
      if (res.status === 401) {
        router.push("/login");
        return;
      }
      if (!res.ok) throw new Error("Failed to create reminder");
      setTitle("");
      setTimeOfDay("08:00");
      setScheduleType("daily");
      await loadReminders();
    } catch (e: any) {
      setError(e.message || "Failed to create");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      const res = await fetch(`${API_URL}/api/reminders/${id}`, {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      if (res.status === 401) {
        router.push("/login");
        return;
      }
      if (!res.ok) throw new Error("Failed to delete");
      setReminders((prev) => prev.filter((r) => r.id !== id));
    } catch (e: any) {
      setError(e.message || "Failed to delete");
    }
  }

  const scheduleLabels: Record<string, string> = {
    daily: "每天",
    weekly: "每周",
    once: "一次",
    interval: "间隔",
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-2xl px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <a href="/chat" className="text-sm text-indigo-500 hover:underline">
            &larr; 返回聊天
          </a>
          <h1 className="mt-2 text-2xl font-bold text-gray-800">提醒管理</h1>
          <p className="mt-1 text-sm text-gray-500">管理您的日常提醒</p>
        </div>

        {/* New Reminder Form */}
        <form
          onSubmit={handleCreate}
          className="mb-8 rounded-xl border border-gray-200 bg-white p-5"
        >
          <h2 className="mb-4 text-base font-semibold text-gray-700">
            新建提醒
          </h2>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-sm text-gray-600">
                提醒内容
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="例如：按时吃药"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm outline-none transition focus:border-indigo-500 focus:shadow-[0_0_0_2px_rgba(99,102,241,0.15)]"
              />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <label className="mb-1 block text-sm text-gray-600">时间</label>
                <input
                  type="time"
                  value={timeOfDay}
                  onChange={(e) => setTimeOfDay(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm outline-none transition focus:border-indigo-500 focus:shadow-[0_0_0_2px_rgba(99,102,241,0.15)]"
                />
              </div>
              <div className="flex-1">
                <label className="mb-1 block text-sm text-gray-600">
                  重复类型
                </label>
                <select
                  value={scheduleType}
                  onChange={(e) => setScheduleType(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm outline-none transition focus:border-indigo-500 focus:shadow-[0_0_0_2px_rgba(99,102,241,0.15)]"
                >
                  <option value="daily">每天</option>
                  <option value="weekly">每周</option>
                  <option value="once">一次</option>
                  <option value="interval">间隔</option>
                </select>
              </div>
            </div>
            <button
              type="submit"
              disabled={creating || !title.trim()}
              className="w-full rounded-lg bg-indigo-500 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-600 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {creating ? "创建中..." : "添加提醒"}
            </button>
          </div>
        </form>

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

        {/* Reminder List */}
        {!loading && reminders.length === 0 && (
          <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-sm text-gray-400">
            还没有提醒，添加一个吧
          </div>
        )}

        {!loading && reminders.length > 0 && (
          <div className="space-y-3">
            {reminders.map((r) => (
              <div
                key={r.id}
                className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-sm font-medium ${
                        r.is_active ? "text-gray-800" : "text-gray-400 line-through"
                      }`}
                    >
                      {r.title}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        r.is_active
                          ? "bg-green-100 text-green-700"
                          : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {r.is_active ? "启用" : "停用"}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-xs text-gray-400">
                    {r.time_of_day && <span>{r.time_of_day}</span>}
                    <span>{scheduleLabels[r.schedule_type] || r.schedule_type}</span>
                    {r.created_by && (
                      <span>
                        {r.created_by === "elder" ? "自己创建" : "家人创建"}
                      </span>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(r.id)}
                  className="ml-3 rounded-lg px-3 py-1.5 text-xs text-red-500 transition hover:bg-red-50"
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
