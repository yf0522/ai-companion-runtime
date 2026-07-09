"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import RoleShell from "@/components/RoleShell";
import { ErrorState, LoadingState } from "@/components/SurfaceStates";
import TraceTimeline from "@/components/TraceTimeline";
import { ApiError, fetchTrace, userFacingApiError } from "@/lib/api-client";

export default function OpsTracePage({ params }: { params: { traceId: string } }) {
  const [trace, setTrace] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchTrace(params.traceId);
        if (!cancelled) setTrace(data);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        if (!cancelled) {
          setError(
            err instanceof ApiError && err.status === 404
              ? "没有找到这条追踪记录。"
              : userFacingApiError(err, "追踪详情加载失败，请稍后重试。"),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [params.traceId, router]);

  return (
    <RoleShell
      role="operator"
      title="追踪详情"
      subtitle={params.traceId}
    >
      {loading && <LoadingState label="正在加载追踪详情" />}
      {error && <ErrorState description={error} />}
      {trace !== null && <TraceTimeline trace={trace as any} />}
    </RoleShell>
  );
}
