# Gmail Multi-Account Manager Design

## Goal

Replace the narrow `gws-gmail-read` skill with a personal Codex skill that manages multiple personal Gmail accounts through one local worker. Support reading, searching, triage, drafts, labels, archive, read state, and sending. Preserve user control over every outbound message.

## Scope

- Support personal `@gmail.com` accounts only.
- Keep OAuth credentials and refresh tokens local and isolated per mailbox.
- Allow read-only operations without confirmation.
- Explain mailbox mutations before applying them; require explicit confirmation for deletion.
- Require a separate, explicit confirmation immediately before sending each email.
- Never permit an automation to send email.
- Do not migrate or reuse existing mailbox refresh tokens from the reference bundle.

## Architecture

Create two personal installation locations:

- `~/.codex/skills/gmail-multi-account-manager`: discoverable skill instructions and UI metadata.
- `~/.codex/gmail-multi-account-manager`: Python worker, virtual environment, runtime registry, OAuth client, and secrets.

Adapt the worker from `/Users/macbook/Downloads/gmail-ai-daily-ops-bundle`. Keep its mailbox registry model: every mailbox has a stable key, email address, label, and private token path. Commands accept `--mailbox`; cross-mailbox orchestration enumerates the active mailbox keys and runs the minimum necessary query against each account.

Do not couple the worker to the current repository. Resolve paths from the installed worker root so the skill works from any workspace.

## Components

### Skill instructions

The skill translates natural-language mailbox goals into worker commands. It must:

- discover connected and active mailboxes before acting;
- identify the mailbox on every result and proposed mutation;
- minimize message-body exposure in terminal output;
- inspect full thread context before drafting or sending;
- keep high-risk mail such as credentials, finance, legal, medical, and account security human-review-first;
- treat user edits to runtime settings as authoritative.

### Mailbox registry

Store non-secret mailbox metadata in `runtime/mailboxes.json`. Store one OAuth token per mailbox under `secrets/mailboxes/`. Set secret directories to mode `0700` and secret files to `0600`. Never print refresh tokens, client secrets, or full token payloads.

Connecting an account opens Google's OAuth browser flow, verifies that the returned profile ends in `@gmail.com`, derives a collision-resistant mailbox key, and registers the token only after successful profile verification.

### Gmail primitives

Provide deterministic commands for:

- connecting and listing mailboxes;
- selecting active mailboxes;
- searching thread snapshots;
- reading a complete thread;
- listing and modifying labels;
- archiving and changing read state;
- creating reply or new-message drafts;
- previewing a draft in a stable confirmation format;
- sending exactly one previously previewed draft.

The send primitive accepts a draft ID and mailbox key, not arbitrary body text. Immediately before sending, it reloads the draft and emits a preview containing mailbox, recipients, CC/BCC, subject, body, and attachments. The skill then asks for explicit confirmation for that one draft. A confirmation cannot authorize another draft or a batch.

### Automation boundary

Scheduled runs may search, summarize, classify, label or archive under an approved policy, and create drafts. The send primitive must reject execution when an automation marker is present. No setting may disable the per-message confirmation rule.

## Operation Flow

### Connect mailbox

1. Read the OAuth desktop client from the installed runtime.
2. Open the browser consent flow with `gmail.modify` and `gmail.send` scopes.
3. Verify the Gmail profile and personal-account constraint.
4. Save the token to a new mailbox-specific secret file.
5. Register and optionally activate the mailbox.
6. Run a read-only profile smoke test.

### Read or triage

1. Resolve requested or active mailboxes.
2. Run a bounded Gmail query against each mailbox.
3. Merge results while retaining mailbox identity.
4. Inspect full threads only where needed.
5. Present findings and performed read-only operations.

### Send

1. Inspect the source thread when replying.
2. Create or update a Gmail draft.
3. Reload and display the canonical draft preview.
4. Ask for explicit confirmation naming the mailbox, recipients, and subject.
5. If confirmed, send only that draft ID and report the Gmail message ID.
6. If content changed after preview, invalidate confirmation and preview again.

## Safety and Error Handling

- Fail closed when mailbox selection is ambiguous.
- Reject unknown mailbox keys and mismatched token/profile identities.
- Never fall back silently from one mailbox to another.
- Do not log message bodies or secrets to persistent runtime reports.
- Keep draft previews in chat only unless the user requests a file.
- On OAuth failure, leave the registry unchanged and remove incomplete token files.
- On API rate limits or transient failures, report the affected mailbox and retry only safe reads automatically.
- Require fresh confirmation after any failed or retried send attempt.

## Testing

Use unit tests with fake Gmail services and temporary runtime directories. Cover:

- independent tokens and routing for two Gmail accounts;
- rejection of non-`gmail.com` profiles;
- ambiguous active-mailbox selection;
- cross-mailbox result attribution;
- draft preview completeness;
- send limited to the previewed draft ID;
- changed-draft confirmation invalidation;
- automation send rejection;
- secret masking and file permissions;
- cleanup after partial OAuth failure.

Run syntax checks, unit tests, skill validation, and read-only smoke tests. Live send testing must stop at draft creation unless the user explicitly approves sending a designated test email.

## Migration

1. Preserve the reference bundle unchanged as source material.
2. Build and validate the replacement skill in a temporary directory.
3. Install the worker and skill into the personal Codex directories.
4. Remove `~/.agents/skills/gws-gmail-read` only after replacement validation passes.
5. Connect each personal Gmail account interactively.
6. Verify each account independently and then verify a cross-mailbox read.

Rollback consists of removing the new skill directory while leaving its runtime and credentials untouched for manual recovery. Credential deletion is a separate destructive action requiring explicit approval.
