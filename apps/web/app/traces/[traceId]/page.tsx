import { redirect } from "next/navigation";

export default async function TraceRedirect({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  redirect(`/ops/traces/${traceId}`);
}
