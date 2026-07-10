import assert from "node:assert/strict";
import test from "node:test";
import {
  API_PATHS,
  makeIdempotencyKey,
  mutationHeaders,
} from "../lib/release-a-contracts.mjs";

test("CareTask routes use canonical product-facing endpoints", () => {
  assert.equal(API_PATHS.careTasks, "/api/care-tasks");
  assert.equal(API_PATHS.careTask("task 1"), "/api/care-tasks/task%201");
  assert.equal(API_PATHS.careTaskComplete("task/1"), "/api/care-tasks/task%2F1/complete");
  assert.equal(API_PATHS.careTaskCancel("task/1"), "/api/care-tasks/task%2F1/cancel");
});

test("Release A care-circle routes match backend contracts", () => {
  assert.equal(API_PATHS.careCircle, "/api/care-circle");
  assert.equal(API_PATHS.careCircleInvites, "/api/care-circle/invites");
  assert.equal(API_PATHS.careCircleInviteAccept("tok/en"), "/api/care-circle/invites/tok%2Fen/accept");
  assert.equal(API_PATHS.careCircleInviteDeny("tok/en"), "/api/care-circle/invites/tok%2Fen/deny");
  assert.equal(API_PATHS.careCircleBinding("bind 1"), "/api/care-circle/bindings/bind%201");
});

test("contacts readiness and operator case routes match Release A contracts", () => {
  assert.equal(API_PATHS.contacts, "/api/contacts");
  assert.equal(API_PATHS.contact("contact 1"), "/api/contacts/contact%201");
  assert.equal(API_PATHS.contactVerification("contact 1"), "/api/contacts/contact%201/verification");
  assert.equal(API_PATHS.contactVerify("contact 1"), "/api/contacts/contact%201/verify");
  assert.equal(API_PATHS.householdReadiness(), "/api/households/readiness");
  assert.equal(API_PATHS.householdReadiness("home 1"), "/api/households/home%201/readiness");
  assert.equal(API_PATHS.operatorCase("case 1"), "/api/operator/cases/case%201");
  assert.equal(API_PATHS.operatorCaseActivities("case 1"), "/api/operator/cases/case%201/activities");
  assert.equal(API_PATHS.operatorCaseTransition("case 1"), "/api/operator/cases/case%201/transition");
});

test("mutation headers always carry JSON content type and idempotency key", () => {
  assert.deepEqual(mutationHeaders("known-key"), {
    "Content-Type": "application/json",
    "Idempotency-Key": "known-key",
  });
  assert.match(makeIdempotencyKey("care-task"), /^care-task-/);
});
