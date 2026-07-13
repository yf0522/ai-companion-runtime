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
  completed_at?: string | null;
  snooze_until?: string | null;
  updated_at?: string | null;
  care_window_date?: string | null;
  reminder_id?: string | null;
  canonical?: "CareTask" | string;
}

export interface CareTaskFetchOptions {
  include_terminal?: boolean;
  includeTerminal?: boolean;
  scope?: "today" | "all";
  limit?: number;
  statuses?: Array<"pending" | "due" | "done" | "snoozed" | "missed" | "cancelled">;
}

export interface CareTaskCreateInput {
  title: string;
  task_type?: string;
  due_at?: string | null;
  notes?: string | null;
  schedule_type?: "once" | "daily" | "weekly" | null;
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
  delivery_status?: string | null;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  acknowledged_by_name?: string | null;
  owner_id?: string | null;
  owner_name?: string | null;
  evidence_href?: string | null;
  delivery_events?: NotificationDeliveryEvent[];
  receipts?: NotificationDeliveryEvent[];
  events?: NotificationDeliveryEvent[];
  delivery?: {
    outbox_id?: string | null;
    state?: string | null;
    provider?: string | null;
    channel?: string | null;
    attempt_count?: number | null;
    last_error?: string | null;
    latest_receipt?: NotificationDeliveryEvent | null;
  };
  evidence?: {
    operator_case_id?: string | null;
    safety_decision_id?: string | null;
    trace_id?: string | null;
    ack_actor_type?: string | null;
  };
}

export interface NotificationDeliveryEvent {
  id?: string;
  event_type?: string;
  status?: string;
  actor_name?: string | null;
  actor?: string | null;
  occurred_at?: string | null;
  created_at?: string | null;
  evidence_href?: string | null;
}

export interface NotificationsResponse {
  user_id: string;
  items: NotificationItem[];
  total: number;
  status: "persisted" | "unavailable" | string;
}

export interface FamilySummaryItem {
  task_id: string;
  title?: string | null;
  task_type: string;
  status: string;
  owner?: string | null;
  due_at: string | null;
  completed_at: string | null;
  evidence?: Record<string, unknown> | null;
  evidence_at?: string | null;
}

export interface FamilySummaryResponse {
  elder_user_id: string;
  family_user_id: string;
  summary: {
    summary_type: "care_outcomes_only";
    total_outcomes: number;
    by_status: Record<string, number>;
    items: FamilySummaryItem[];
    range?: string;
    range_basis?: string;
    denominator?: number;
    completion?: {
      completed: number;
      rate: number | null;
    };
    trend?: {
      previous_denominator: number | null;
      previous_rate: number | null;
      delta: number | null;
      direction: "up" | "down" | "flat" | "unavailable" | string;
    };
  };
  range?: string | null;
  range_start?: string | null;
  range_end?: string | null;
}

export type FamilySummaryRange =
  | "7d"
  | "30d"
  | "90d"
  | "all"
  | string
  | { from?: string; to?: string; days?: number };

export interface OperatorCaseItem {
  id: string;
  user_id: string;
  elder_user_id?: string | null;
  household_id?: string | null;
  safety_decision_id: string | null;
  notification_outbox_id: string | null;
  trace_id?: string | null;
  status: string;
  severity: string;
  owner_id: string | null;
  ownership_status?: "unassigned" | "owned_by_me" | "owned_by_other" | string;
  allowed_transitions?: string[];
  can_add_activity?: boolean;
  summary: string | null;
  resolution: string | null;
  due_at: string | null;
  created_at: string | null;
  resolved_at: string | null;
  state_version?: number;
  next_action?: string | null;
  evidence?: OperatorCaseEvidence | null;
}

export interface OperatorCaseEvidence {
  safety_decision?: {
    id?: string | null;
    trace_id?: string | null;
    policy_version?: string | null;
    risk_category?: string | null;
    action?: string | null;
    confidence?: number | null;
    calibration?: string | null;
    evidence_ref?: string | null;
  };
  notification_delivery?: {
    outbox_id?: string | null;
    state?: string | null;
    provider?: string | null;
    channel?: string | null;
    attempt_count?: number | null;
    last_error?: string | null;
    updated_at?: string | null;
  };
}

export interface OperatorCasesResponse {
  items: OperatorCaseItem[];
  total: number;
}

export type PlatformReadinessStatus = "ready" | "degraded" | "unsafe_to_serve";

export interface OperatorPlatformReadinessCheck {
  id: string;
  label: string;
  status: PlatformReadinessStatus;
  summary: string;
  duration_ms: number;
  owner: string;
  next_action: string;
  runbook: string;
  observed?: Record<string, string | number | boolean | string[]>;
}

export interface OperatorPlatformReadinessResponse {
  contract_version: "operator-platform-readiness.v1";
  scope: "platform";
  status: PlatformReadinessStatus;
  checked_at: string;
  stale_after_seconds: number;
  future_skew_seconds: number;
  duration_ms: number;
  checks: OperatorPlatformReadinessCheck[];
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
  user_id?: string | null;
  consent_status?: string | null;
  updated_at?: string | null;
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
  permissions: CareCirclePermission[] | string[];
  invites?: CareCircleInvite[];
  current_user?: {
    user_id: string;
    role: string;
    consent_status: string;
  };
  current_binding_id?: string | null;
  can_invite?: boolean;
  can_manage_permissions?: boolean;
  active_bindings?: Array<{
    id: string;
    family_user_id: string;
    elder_user_id: string;
    permissions: string[];
    status: string;
    consent_status: string;
    version?: number;
  }>;
  capabilities?: Record<string, boolean>;
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
  escalation_order?: number | null;
  available: boolean;
  last_verified_at: string | null;
  challenge_code_dev?: string;
  user_id?: string | null;
  household_id?: string | null;
  resource_type?: string;
  kind?: string;
  label?: string | null;
  priority?: number | null;
  status?: string | null;
  availability?: Record<string, unknown>;
  verification_state?: string | null;
  verified_at?: string | null;
  revoked_at?: string | null;
  updated_at?: string | null;
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
  owner?: string | null;
  action?: string | null;
  next_action?: string | null;
  evidence?: Record<string, unknown> | string | null;
  evidence_at?: string | null;
  updated_at?: string | null;
}

export interface HouseholdReadinessResponse {
  household_id: string;
  status: "ready" | "not_ready" | "blocked" | string;
  checks: HouseholdReadinessCheck[];
  next_action: string | null;
  updated_at: string | null;
  owner?: string | null;
  evidence?: Record<string, unknown> | null;
}

export interface EmergencyContact {
  id: string;
  resource_type?: "emergency_contact" | string;
  contact_point_id?: string | null;
  name: string;
  phone?: string | null;
  relation?: string | null;
  priority?: number | null;
  availability?: Record<string, unknown>;
  notify_on_levels?: string[];
  verification_state?: string | null;
  verified_at?: string | null;
  is_active?: boolean;
  updated_at?: string | null;
}

export interface EmergencyContactsResponse {
  items: EmergencyContact[];
  total: number;
}

export interface EscalationStep {
  step_order: number;
  action: string;
  contact_point_id?: string | null;
  delay_seconds?: number;
  config?: Record<string, unknown>;
}

export interface EscalationPolicy {
  id: string;
  household_id: string;
  name?: string | null;
  version: number;
  status: string;
  steps: EscalationStep[];
  updated_at?: string | null;
}

export interface EscalationPoliciesResponse {
  items: EscalationPolicy[];
  total: number;
}

export interface MemoryItem {
  id: string;
  content: string;
  type?: string | null;
  importance?: number;
  purpose?: string | null;
  sensitivity?: string | null;
  consent_status: "pending" | "granted" | "rejected" | string;
  retention_until?: string | null;
  retention_status?: "active" | "unbounded" | "expired" | string;
  retrievable?: boolean;
  correction_state?: string | null;
  deletion_state?: string | null;
  embedding_state?: string | null;
  source?: string | null;
  source_trace_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  status?: string | null;
  lifecycle_status?: string | null;
}

export interface MemoriesResponse {
  user_id: string;
  memories: MemoryItem[];
  items?: MemoryItem[];
}

export interface OperatorCaseActivity {
  id: string;
  case_id: string;
  actor_type: "system" | "operator" | "caregiver" | "elder" | string;
  actor_id: string | null;
  activity_type: string;
  from_status?: string | null;
  to_status?: string | null;
  summary: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface OperatorCaseDetail extends OperatorCaseItem {
  evidence?: OperatorCaseEvidence | null;
}

export interface OperatorCaseActivitiesResponse {
  items: OperatorCaseActivity[];
  total: number;
}

export interface OperatorHouseholdItem {
  id: string;
  name: string;
  elder_user_id: string;
  elder_name: string;
  status: string;
  updated_at: string | null;
  readiness_href?: string | null;
}

export interface OperatorHouseholdsResponse {
  scope: "operator_household_discovery" | string;
  query?: string | null;
  items: OperatorHouseholdItem[];
  total: number;
}

export interface TraceListItem {
  trace_id: string;
  started_at: string | null;
  event_count: number | null;
  failed_event_count: number | null;
  status: string;
  user_id: string | null;
  case_id: string | null;
  case_ids: string[];
  case_status: string | null;
  severity: string | null;
}

export interface TraceListResponse {
  contract_version?: string;
  scope: "self" | "operator_case" | string;
  items: TraceListItem[];
  traces?: TraceListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TraceAuthorization {
  scope: "self" | "operator_case" | string;
  case_id: string | null;
  case_ids: string[];
  audited: boolean;
}

export interface TraceEventData {
  step_name?: string;
  step_index?: number;
  status?: string;
  latency_ms?: number | null;
  output?: unknown;
  error?: string | null;
}

export interface TraceModelCall {
  provider?: string;
  model?: string;
  role?: string;
  prompt_tokens?: number | null;
  output_tokens?: number | null;
  ttft_ms?: number | null;
  total_latency_ms?: number | null;
  status?: string;
  cost_cents?: number | null;
}

export interface TraceToolCall {
  tool_name?: string;
  status?: string;
  latency_ms?: number | null;
}

export interface TraceDetailResponse {
  trace_id?: string;
  user_id?: string | null;
  session_id?: string | null;
  started_at?: string | null;
  total_latency_ms?: number | null;
  events?: TraceEventData[];
  model_calls?: TraceModelCall[];
  tool_calls?: TraceToolCall[];
  cost_summary?: {
    total_tokens?: number | null;
    total_cost_cents?: number | null;
  };
  authorization?: TraceAuthorization;
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

export async function fetchTrace(traceId: string): Promise<TraceDetailResponse> {
  const res = await fetch(`${API_URL}/api/traces/${traceId}`, {
    headers: getAuthHeaders(),
  });
  return readJson<TraceDetailResponse>(res);
}

export async function fetchTraces(limit = 20, offset = 0): Promise<TraceListResponse> {
  const res = await fetch(`${API_URL}/api/traces?limit=${limit}&offset=${offset}`, {
    headers: getAuthHeaders(),
  });
  const payload = await readJson<Partial<TraceListResponse>>(res);
  const items = payload.items || payload.traces || [];
  return {
    scope: payload.scope || "self",
    items,
    traces: payload.traces || items,
    total: payload.total ?? items.length,
    limit: payload.limit ?? limit,
    offset: payload.offset ?? offset,
    contract_version: payload.contract_version,
  };
}

export async function fetchCareTasks(options: CareTaskFetchOptions = {}): Promise<CareTaskItem[]> {
  const params = new URLSearchParams();
  const includeTerminal = options.include_terminal ?? options.includeTerminal;
  if (includeTerminal !== undefined) params.set("include_terminal", String(includeTerminal));
  if (options.scope) params.set("scope", options.scope);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  for (const status of options.statuses || []) params.append("statuses", status);
  const query = params.toString();
  const res = await fetch(`${API_URL}${API_PATHS.careTasks}${query ? `?${query}` : ""}`, {
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

export async function snoozeCareTask(
  id: string,
  input: CareTaskMutationInput & { minutes: number },
): Promise<Partial<CareTaskItem>> {
  const idempotencyKey = input.idempotency_key || makeIdempotencyKey("care-task-snooze");
  const { idempotency_key: _unused, ...body } = input;
  const res = await fetch(`${API_URL}${API_PATHS.careTaskSnooze(id)}`, {
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
    ...payload,
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

export async function fetchEmergencyContacts(): Promise<EmergencyContactsResponse> {
  const res = await fetch(`${API_URL}${API_PATHS.contacts}/emergency`, {
    headers: authHeaders(),
  });
  const payload = await readJson<EmergencyContactsResponse | EmergencyContact[]>(res);
  return Array.isArray(payload)
    ? { items: payload, total: payload.length }
    : { ...payload, items: payload.items || [], total: payload.total || payload.items?.length || 0 };
}

export async function fetchEscalationPolicies(
  householdId: string,
): Promise<EscalationPoliciesResponse> {
  const res = await fetch(
    `${API_URL}/api/households/${encodeURIComponent(householdId)}/escalation-policies`,
    { headers: authHeaders() },
  );
  const payload = await readJson<EscalationPoliciesResponse | EscalationPolicy[]>(res);
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
    priority: source.priority || 1,
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

export async function fetchMemories(limit = 50): Promise<MemoriesResponse> {
  const params = new URLSearchParams({ limit: String(Math.max(1, Math.min(limit, 100))) });
  const res = await fetch(`${API_URL}/api/memory/memories?${params}`, {
    headers: authHeaders(),
  });
  const payload = await readJson<Partial<MemoriesResponse>>(res);
  const memories = payload.memories || payload.items || [];
  return { user_id: payload.user_id || "", memories, items: payload.items || memories };
}

export async function decideMemoryConsent(
  memoryId: string,
  approved: boolean,
): Promise<{ memory_id: string; consent_status: string; consent_grant_id?: string | null }> {
  const res = await fetch(`${API_URL}/api/memory/memories/${encodeURIComponent(memoryId)}/consent`, {
    method: "POST",
    headers: authHeaders(true),
    body: JSON.stringify({ approved }),
  });
  return readJson(res);
}

export async function correctMemory(
  memoryId: string,
  correctedContent: string,
  reason?: string,
): Promise<{ memory_id: string; correction_state: string }> {
  const res = await fetch(`${API_URL}/api/memory/memories/${encodeURIComponent(memoryId)}/correction`, {
    method: "PATCH",
    headers: authHeaders(true),
    body: JSON.stringify({
      corrected_content: correctedContent,
      ...(reason?.trim() ? { reason: reason.trim() } : {}),
    }),
  });
  return readJson(res);
}

export async function deleteMemory(
  memoryId: string,
): Promise<{ memory_id: string; deletion_state: string; embedding_state?: string }> {
  const res = await fetch(`${API_URL}/api/memory/memories/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return readJson(res);
}

export async function fetchFamilySummary(
  range?: FamilySummaryRange,
): Promise<FamilySummaryResponse> {
  const params = new URLSearchParams();
  if (typeof range === "string" && range) params.set("range", range);
  if (range && typeof range === "object") {
    if (range.from) params.set("from", range.from);
    if (range.to) params.set("to", range.to);
    if (range.days !== undefined) params.set("days", String(range.days));
  }
  const query = params.toString();
  const res = await fetch(`${API_URL}/api/memory/family-summary${query ? `?${query}` : ""}`, {
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

export async function fetchOperatorPlatformReadiness(): Promise<OperatorPlatformReadinessResponse> {
  const res = await fetch(`${API_URL}/api/operator/platform/readiness`, {
    headers: authHeaders(),
    cache: "no-store",
  });
  return readJson<OperatorPlatformReadinessResponse>(res);
}

export async function fetchOperatorHouseholds(query = ""): Promise<OperatorHouseholdsResponse> {
  const params = new URLSearchParams({ limit: "100" });
  if (query.trim()) params.set("query", query.trim());
  const res = await fetch(`${API_URL}/api/households?${params}`, {
    headers: authHeaders(),
  });
  return readJson<OperatorHouseholdsResponse>(res);
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
