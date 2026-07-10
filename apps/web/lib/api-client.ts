import { API_PATHS, makeIdempotencyKey, mutationHeaders } from "./release-a-contracts.mjs";

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

export interface CareTaskItem {
  id: string;
  title: string;
  task_type?: string | null;
  description?: string | null;
  notes?: string | null;
  schedule_type?: string | null;
  time_of_day?: string | null;
  due_at?: string | null;
  next_fire_at?: string | null;
  status?: string;
  is_active?: boolean;
  expected_version?: number;
  version?: number;
  created_by?: string | null;
  created_at?: string | null;
}

export interface CareTaskCreateInput {
  title: string;
  task_type?: string;
  due_at?: string | null;
  notes?: string | null;
  schedule_type?: "once" | "daily" | "weekly" | "interval" | string | null;
  query?: string | null;
  idempotency_key?: string;
}

export interface CareTaskMutationInput {
  expected_version: number;
  idempotency_key?: string;
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
  state_version?: number;
}

export interface OperatorCasesResponse {
  items: OperatorCaseItem[];
  total: number;
}

export interface CareCircleMember {
  id: string;
  name: string;
  binding_id?: string | null;
  relationship?: string | null;
  role: "elder" | "primary_caregiver" | "caregiver" | "operator" | string;
  status: "active" | "invited" | "paused" | string;
  permissions: string[];
  escalation_order: number | null;
}

export interface CareCirclePermission {
  id: string;
  subject_id: string;
  scope: string;
  granted: boolean;
  granted_by: string | null;
  updated_at: string | null;
}

export interface CareCircleResponse {
  household_id: string;
  members: CareCircleMember[];
  permissions: CareCirclePermission[];
  invites?: CareCircleInvite[];
}

export interface CareCircleInvite {
  token?: string;
  email?: string | null;
  phone?: string | null;
  role: string;
  status: string;
  expires_at?: string | null;
}

export interface VerifiedContact {
  id: string;
  name: string;
  channel: "phone" | "sms" | "email" | "wechat" | string;
  value: string;
  verification_status: "verified" | "pending" | "failed" | "unverified" | string;
  escalation_order: number | null;
  available: boolean;
  last_verified_at: string | null;
  challenge_code_dev?: string;
}

export interface ContactsResponse {
  items: VerifiedContact[];
  total: number;
}

export interface HouseholdReadinessCheck {
  key: string;
  label: string;
  status: "ready" | "missing" | "warning" | "blocked" | string;
  detail: string | null;
  required: boolean;
}

export interface HouseholdReadinessResponse {
  household_id: string;
  status: "ready" | "not_ready" | "blocked" | string;
  checks: HouseholdReadinessCheck[];
  next_action: string | null;
  updated_at: string | null;
}

export interface OperatorCaseActivity {
  id: string;
  case_id: string;
  actor_type: "system" | "operator" | "caregiver" | "elder" | string;
  actor_id: string | null;
  activity_type: string;
  summary: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface OperatorCaseDetail extends OperatorCaseItem {
  household_id?: string | null;
  elder_user_id?: string | null;
  next_action?: string | null;
  evidence?: Record<string, unknown> | null;
}

export interface OperatorCaseActivitiesResponse {
  items: OperatorCaseActivity[];
  total: number;
}

function authHeaders(contentType = false): HeadersInit {
  return {
    ...getAuthHeaders(),
    ...(contentType ? { "Content-Type": "application/json" } : {}),
  };
}

function authMutationHeaders(idempotencyKey?: string): HeadersInit {
  return {
    ...getAuthHeaders(),
    ...mutationHeaders(idempotencyKey),
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

function listFromEnvelope<T>(payload: T[] | { items?: T[]; results?: T[] }): T[] {
  if (Array.isArray(payload)) return payload;
  return payload.items || payload.results || [];
}

function expectedVersionFor(task: CareTaskItem): number {
  return task.expected_version || task.version || 1;
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

export async function fetchCareTasks(): Promise<CareTaskItem[]> {
  const res = await fetch(`${API_URL}${API_PATHS.careTasks}`, {
    headers: authHeaders(),
  });
  const payload = await readJson<CareTaskItem[] | { items?: CareTaskItem[] }>(res);
  return listFromEnvelope(payload);
}

export async function createCareTask(
  input: CareTaskCreateInput,
): Promise<Partial<CareTaskItem>> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("care-task-create");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.careTasks}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<Partial<CareTaskItem>>(res);
}

export async function updateCareTask(
  id: string,
  input: Partial<CareTaskCreateInput> & CareTaskMutationInput & { status?: string },
): Promise<Partial<CareTaskItem>> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("care-task-update");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.careTask(id)}`, {
    method: "PATCH",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<Partial<CareTaskItem>>(res);
}

export async function cancelCareTask(
  id: string,
  input: CareTaskMutationInput,
): Promise<Partial<CareTaskItem>> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("care-task-cancel");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.careTaskCancel(id)}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<Partial<CareTaskItem>>(res);
}

export async function completeCareTask(
  id: string,
  input: CareTaskMutationInput,
): Promise<Partial<CareTaskItem>> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("care-task-complete");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.careTaskComplete(id)}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<Partial<CareTaskItem>>(res);
}

export function mutationInputForTask(
  task: CareTaskItem,
  idempotencyPrefix: string,
): CareTaskMutationInput {
  return {
    expected_version: expectedVersionFor(task),
    idempotency_key: makeIdempotencyKey(idempotencyPrefix),
  };
}

export async function fetchCareCircle(): Promise<CareCircleResponse> {
  const res = await fetch(`${API_URL}${API_PATHS.careCircle}`, {
    headers: authHeaders(),
  });
  const payload = await readJson<Partial<CareCircleResponse> & { items?: CareCircleMember[] }>(res);
  return {
    household_id: payload.household_id || "",
    members: payload.members || payload.items || [],
    permissions: payload.permissions || [],
    invites: payload.invites || [],
  };
}

export async function inviteCareCircleMember(input: {
  email?: string;
  role: string;
  permissions: string[];
  idempotency_key?: string;
}): Promise<CareCircleInvite> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("care-circle-invite");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.careCircleInvites}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<CareCircleInvite>(res);
}

export async function acceptCareCircleInvite(
  token: string,
  idempotencyKey = makeIdempotencyKey("care-circle-accept"),
): Promise<CareCircleMember> {
  const res = await fetch(`${API_URL}${API_PATHS.careCircleInviteAccept(token)}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify({}),
  });
  return readJson<CareCircleMember>(res);
}

export async function denyCareCircleInvite(
  token: string,
  idempotencyKey = makeIdempotencyKey("care-circle-deny"),
): Promise<{ denied: boolean }> {
  const res = await fetch(`${API_URL}${API_PATHS.careCircleInviteDeny(token)}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify({}),
  });
  return readJson<{ denied: boolean }>(res);
}

export async function updateCareCircleBinding(
  bindingId: string,
  input: { permissions?: string[]; role?: string; escalation_order?: number | null; idempotency_key?: string },
): Promise<CareCircleMember> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("care-circle-binding");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.careCircleBinding(bindingId)}`, {
    method: "PATCH",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<CareCircleMember>(res);
}

export async function revokeCareCircleBinding(
  bindingId: string,
  idempotencyKey = makeIdempotencyKey("care-circle-revoke"),
): Promise<{ revoked: boolean }> {
  const res = await fetch(`${API_URL}${API_PATHS.careCircleBinding(bindingId)}`, {
    method: "DELETE",
    headers: {
      ...getAuthHeaders(),
      "Idempotency-Key": idempotencyKey,
    },
  });
  return readJson<{ revoked: boolean }>(res);
}

export async function fetchContacts(): Promise<ContactsResponse> {
  const res = await fetch(`${API_URL}${API_PATHS.contacts}`, {
    headers: authHeaders(),
  });
  const payload = await readJson<ContactsResponse | VerifiedContact[]>(res);
  return Array.isArray(payload)
    ? { items: payload, total: payload.length }
    : { ...payload, items: payload.items || [], total: payload.total || payload.items?.length || 0 };
}

export async function createContact(
  input: Omit<VerifiedContact, "id" | "verification_status" | "last_verified_at"> & {
    idempotency_key?: string;
  },
): Promise<VerifiedContact> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("contact-create");
  const { idempotency_key: _unused, ...source } = input;
  const body = {
    kind: source.channel,
    value: source.value,
    label: source.name,
    priority: source.escalation_order || 1,
    availability: { available: source.available },
  };
  const res = await fetch(`${API_URL}${API_PATHS.contacts}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<VerifiedContact>(res);
}

export async function requestContactVerification(
  id: string,
  idempotencyKey = makeIdempotencyKey("contact-verify"),
): Promise<VerifiedContact> {
  const res = await fetch(`${API_URL}${API_PATHS.contactVerification(id)}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify({}),
  });
  return readJson<VerifiedContact>(res);
}

export async function confirmContactVerification(
  id: string,
  code: string,
  idempotencyKey = makeIdempotencyKey("contact-confirm"),
): Promise<VerifiedContact> {
  const res = await fetch(`${API_URL}${API_PATHS.contactVerify(id)}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify({ code }),
  });
  return readJson<VerifiedContact>(res);
}

export async function deleteContact(
  id: string,
  idempotencyKey = makeIdempotencyKey("contact-delete"),
): Promise<{ deleted: boolean }> {
  const res = await fetch(`${API_URL}${API_PATHS.contact(id)}`, {
    method: "DELETE",
    headers: {
      ...getAuthHeaders(),
      "Idempotency-Key": idempotencyKey,
    },
  });
  return readJson<{ deleted: boolean }>(res);
}

export async function fetchHouseholdReadiness(householdId?: string): Promise<HouseholdReadinessResponse> {
  const res = await fetch(`${API_URL}${API_PATHS.householdReadiness(householdId)}`, {
    headers: authHeaders(),
  });
  return readJson<HouseholdReadinessResponse>(res);
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
  const res = await fetch(`${API_URL}${API_PATHS.operatorCases}`, {
    headers: authHeaders(),
  });
  return readJson<OperatorCasesResponse>(res);
}

export async function fetchOperatorCase(caseId: string): Promise<OperatorCaseDetail> {
  const res = await fetch(`${API_URL}${API_PATHS.operatorCase(caseId)}`, {
    headers: authHeaders(),
  });
  return readJson<OperatorCaseDetail>(res);
}

export async function fetchOperatorCaseActivities(
  caseId: string,
): Promise<OperatorCaseActivitiesResponse> {
  const res = await fetch(`${API_URL}${API_PATHS.operatorCaseActivities(caseId)}`, {
    headers: authHeaders(),
  });
  return readJson<OperatorCaseActivitiesResponse>(res);
}

export async function createOperatorCaseActivity(
  caseId: string,
  input: { activity_type: string; summary: string; metadata?: Record<string, unknown>; idempotency_key?: string },
): Promise<OperatorCaseActivity> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("case-activity");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.operatorCaseActivities(caseId)}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<OperatorCaseActivity>(res);
}

export async function transitionOperatorCase(
  caseId: string,
  input: { status: string; expected_state_version: number; resolution?: string | null; idempotency_key?: string },
): Promise<Partial<OperatorCaseDetail>> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("case-transition");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.operatorCaseTransition(caseId)}`, {
    method: "POST",
    headers: authMutationHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  return readJson<Partial<OperatorCaseDetail>>(res);
}
