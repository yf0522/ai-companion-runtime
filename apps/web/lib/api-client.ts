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

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function userFacingApiError(
  error: unknown,
  fallback = "服务暂时不可用，请稍后重试。",
): string {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }
  if (error instanceof TypeError) {
    return "无法连接服务。这不是空数据，请检查网络后重试。";
  }
  return fallback;
}

export interface ReminderItem {
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

export interface ReminderCreateInput {
  title: string;
  time_of_day: string;
  schedule_type: string;
  description?: string | null;
}

export interface NotificationItem {
  id: string;
  user_id: string;
  category: string;
  title: string;
  message: string;
  trace_id: string | null;
  severity: string;
  status: string;
  created_at: string;
}

export interface NotificationsResponse {
  user_id: string;
  items: NotificationItem[];
  total: number;
  status: "persisted" | "unavailable" | string;
}

export interface FamilySummaryItem {
  task_id: string;
  task_type: string;
  status: string;
  due_at: string | null;
  completed_at: string | null;
}

export interface FamilySummaryResponse {
  elder_user_id: string;
  family_user_id: string;
  summary: {
    summary_type: "care_outcomes_only";
    total_outcomes: number;
    by_status: Record<string, number>;
    items: FamilySummaryItem[];
  };
}

export interface OperatorCaseItem {
  id: string;
  user_id: string;
  safety_decision_id: string | null;
  notification_outbox_id: string | null;
  status: string;
  severity: string;
  owner_id: string | null;
  summary: string | null;
  resolution: string | null;
  due_at: string | null;
  created_at: string | null;
  resolved_at: string | null;
}

export interface OperatorCasesResponse {
  items: OperatorCaseItem[];
  total: number;
}

function authHeaders(contentType = false): HeadersInit {
  return {
    ...getAuthHeaders(),
    ...(contentType ? { "Content-Type": "application/json" } : {}),
  };
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const message =
      typeof body?.detail === "string" ? body.detail : res.statusText;
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export async function fetchTrace(traceId: string) {
  const res = await fetch(`${API_URL}/api/traces/${traceId}`, {
    headers: getAuthHeaders(),
  });
  return readJson(res);
}

export async function fetchTraces(limit = 20, offset = 0) {
  const res = await fetch(`${API_URL}/api/traces?limit=${limit}&offset=${offset}`, {
    headers: getAuthHeaders(),
  });
  return readJson(res);
}

export async function fetchReminders(): Promise<ReminderItem[]> {
  const res = await fetch(`${API_URL}/api/reminders`, {
    headers: authHeaders(),
  });
  return readJson<ReminderItem[]>(res);
}

export async function createReminder(
  input: ReminderCreateInput,
): Promise<Partial<ReminderItem>> {
  const res = await fetch(`${API_URL}/api/reminders`, {
    method: "POST",
    headers: authHeaders(true),
    body: JSON.stringify(input),
  });
  return readJson<Partial<ReminderItem>>(res);
}

export async function updateReminder(
  id: string,
  input: Partial<ReminderCreateInput> & { is_active?: boolean },
): Promise<Partial<ReminderItem>> {
  const res = await fetch(`${API_URL}/api/reminders/${id}`, {
    method: "PUT",
    headers: authHeaders(true),
    body: JSON.stringify(input),
  });
  return readJson<Partial<ReminderItem>>(res);
}

export async function deleteReminder(id: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${API_URL}/api/reminders/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return readJson<{ deleted: boolean }>(res);
}

export async function acknowledgeReminder(
  id: string,
): Promise<{ status: string; reminder_id: string; history_id: string }> {
  const res = await fetch(`${API_URL}/api/reminders/${id}/ack`, {
    method: "POST",
    headers: authHeaders(),
  });
  return readJson(res);
}

export async function fetchNotifications(): Promise<NotificationsResponse> {
  const res = await fetch(`${API_URL}/api/notifications`, {
    headers: authHeaders(),
  });
  return readJson<NotificationsResponse>(res);
}

export async function acknowledgeNotification(
  id: string,
): Promise<{ status: string; item?: NotificationItem }> {
  const res = await fetch(`${API_URL}/api/notifications/${id}/ack`, {
    method: "POST",
    headers: authHeaders(),
  });
  return readJson(res);
}

export async function fetchFamilySummary(): Promise<FamilySummaryResponse> {
  const res = await fetch(`${API_URL}/api/memory/family-summary`, {
    headers: authHeaders(),
  });
  return readJson<FamilySummaryResponse>(res);
}

export async function fetchOperatorCases(): Promise<OperatorCasesResponse> {
  const res = await fetch(`${API_URL}/api/operator/cases`, {
    headers: authHeaders(),
  });
  return readJson<OperatorCasesResponse>(res);
}
