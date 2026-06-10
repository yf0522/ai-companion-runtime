"use client";

import { useEffect, useState } from "react";
import TraceTimeline from "@/components/TraceTimeline";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function TracePage({ params }: { params: { traceId: string } }) {
  const [trace, setTrace] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${API_URL}/api/traces/${params.traceId}`);
        if (!res.ok) {
          setError(res.status === 404 ? "Trace 未找到" : "加载失败");
          return;
        }
        setTrace(await res.json());
      } catch (e) {
        setError("无法连接到服务器");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [params.traceId]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-4xl px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <a href="/chat" className="text-sm text-blue-500 hover:underline">
            ← 返回聊天
          </a>
          <h1 className="mt-2 text-2xl font-bold text-gray-800">链路追踪</h1>
          <p className="mt-1 font-mono text-sm text-gray-500">
            {params.traceId}
          </p>
        </div>

        {/* Content */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-600">
            {error}
          </div>
        )}

        {trace && <TraceTimeline trace={trace} />}
      </div>
    </div>
  );
}
