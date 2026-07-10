export const API_PATHS = {
  careTasks: "/api/care-tasks",
  careTask: (taskId) => `/api/care-tasks/${encodeURIComponent(taskId)}`,
  careTaskComplete: (taskId) => `/api/care-tasks/${encodeURIComponent(taskId)}/complete`,
  careTaskSnooze: (taskId) => `/api/care-tasks/${encodeURIComponent(taskId)}/snooze`,
  careTaskCancel: (taskId) => `/api/care-tasks/${encodeURIComponent(taskId)}/cancel`,
  careCircle: "/api/care-circle",
  careCircleInvites: "/api/care-circle/invites",
  careCircleInviteAccept: (token) =>
    `/api/care-circle/invites/${encodeURIComponent(token)}/accept`,
  careCircleInviteDeny: (token) =>
    `/api/care-circle/invites/${encodeURIComponent(token)}/deny`,
  careCircleBinding: (bindingId) =>
    `/api/care-circle/bindings/${encodeURIComponent(bindingId)}`,
  contacts: "/api/contacts",
  contact: (contactId) => `/api/contacts/${encodeURIComponent(contactId)}`,
  contactVerification: (contactId) =>
    `/api/contacts/${encodeURIComponent(contactId)}/verification`,
  contactVerify: (contactId) => `/api/contacts/${encodeURIComponent(contactId)}/verify`,
  householdReadiness: (householdId) =>
    householdId
      ? `/api/households/${encodeURIComponent(householdId)}/readiness`
      : "/api/households/readiness",
  operatorCases: "/api/operator/cases",
  operatorCase: (caseId) => `/api/operator/cases/${encodeURIComponent(caseId)}`,
  operatorCaseTransition: (caseId) =>
    `/api/operator/cases/${encodeURIComponent(caseId)}/transition`,
  operatorCaseActivities: (caseId) =>
    `/api/operator/cases/${encodeURIComponent(caseId)}/activities`,
};

export function makeIdempotencyKey(prefix = "web") {
  const crypto = globalThis.crypto;
  if (crypto && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function mutationHeaders(idempotencyKey = makeIdempotencyKey()) {
  return {
    "Content-Type": "application/json",
    "Idempotency-Key": idempotencyKey,
  };
}
