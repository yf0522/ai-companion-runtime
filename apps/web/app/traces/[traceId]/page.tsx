import { redirect } from "next/navigation";

export default function TraceRedirect({ params }: { params: { traceId: string } }) {
  redirect(`/ops/traces/${params.traceId}`);
}
