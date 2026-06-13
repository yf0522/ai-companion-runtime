const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getAuthHeaders(): HeadersInit {
  // Read token from persisted zustand store in localStorage
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
    // ignore parse errors
  }
  return {};
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function fetchTrace(traceId: string) {
  const res = await fetch(`${API_URL}/api/traces/${traceId}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.json();
}

export async function fetchTraces(limit = 20, offset = 0) {
  const res = await fetch(`${API_URL}/api/traces?limit=${limit}&offset=${offset}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.json();
}
