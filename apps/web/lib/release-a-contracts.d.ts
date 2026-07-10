export const API_PATHS: {
  careTasks: string;
  careTask(taskId: string): string;
  careTaskComplete(taskId: string): string;
  careTaskSnooze(taskId: string): string;
  careTaskCancel(taskId: string): string;
  careCircle: string;
  careCircleInvites: string;
  careCircleInviteAccept(token: string): string;
  careCircleInviteDeny(token: string): string;
  careCircleBinding(bindingId: string): string;
  contacts: string;
  contact(contactId: string): string;
  contactVerification(contactId: string): string;
  contactVerify(contactId: string): string;
  householdReadiness(householdId?: string): string;
  operatorCases: string;
  operatorCase(caseId: string): string;
  operatorCaseTransition(caseId: string): string;
  operatorCaseActivities(caseId: string): string;
};

export function makeIdempotencyKey(prefix?: string): string;
export function mutationHeaders(idempotencyKey?: string): Record<string, string>;
