const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchTrace(traceId: string) {
  const res = await fetch(`${API_URL}/api/traces/${traceId}`);
  if (!res.ok) throw new Error(`Failed to fetch trace: ${res.statusText}`);
  return res.json();
}

export async function fetchTraces(userId: string, limit = 20, offset = 0) {
  const res = await fetch(`${API_URL}/api/traces?user_id=${userId}&limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error(`Failed to fetch traces: ${res.statusText}`);
  return res.json();
}
