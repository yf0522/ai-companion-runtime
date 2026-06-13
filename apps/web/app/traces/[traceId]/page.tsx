"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchTrace } from "@/lib/api-client";
import TraceTimeline from "@/components/TraceTimeline";

export default function TracePage({ params }: { params: { traceId: string } }) {
  const [trace, setTrace] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchTrace(params.traceId);
        setTrace(data);
      } catch (e: any) {
        if (e.status === 401) {
          router.push("/login");
          return;
        }
        setError(e.status === 404 ? "Trace not found" : "Failed to load");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [params.traceId, router]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="mb-6">
          <a href="/chat" className="text-sm text-blue-500 hover:underline">
            &larr; Back to chat
          </a>
          <h1 className="mt-2 text-2xl font-bold text-gray-800">Trace</h1>
          <p className="mt-1 font-mono text-sm text-gray-500">
            {params.traceId}
          </p>
        </div>

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
