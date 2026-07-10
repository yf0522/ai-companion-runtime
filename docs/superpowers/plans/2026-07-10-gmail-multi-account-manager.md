# Gmail Multi-Account Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-message Gmail read skill with a personal Codex skill and local worker that safely manages multiple personal Gmail accounts and sends only one explicitly confirmed draft at a time.

**Architecture:** Adapt the supplied Gmail AI worker into a standalone runtime at `~/.codex/gmail-multi-account-manager`, with one OAuth token per mailbox and deterministic CLI primitives. Install a concise orchestration skill at `~/.codex/skills/gmail-multi-account-manager`; build and test everything in `/private/tmp/gmail-multi-account-manager-build` before replacing the old skill.

**Tech Stack:** Python 3, Google Gmail API client, pytest, Codex skill Markdown/YAML, local Desktop OAuth.

## Global Constraints

- Support personal `@gmail.com` accounts only.
- Keep OAuth credentials and refresh tokens local and isolated per mailbox.
- Read-only operations may run without confirmation.
- Require explicit confirmation for deletion.
- Require a separate explicit confirmation immediately before sending each email.
- Never allow an automation to send email.
- Do not migrate or reuse refresh tokens from the reference bundle.
- Never print refresh tokens, client secrets, or full token payloads.

---

### Task 1: Stage the Worker and Establish Mailbox-Isolation Tests

**Files:**
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/gmail_ai_worker/config.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/gmail_ai_worker/mailboxes.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/tests/test_mailboxes.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/requirements.txt`

**Interfaces:**
- Produces: `MailboxRegistry(runtime_dir: Path, secrets_dir: Path)`, `register(email: str, token_payload: str) -> dict`, `resolve(key: str) -> Path`, and `active_keys() -> list[str]`.
- Produces: mailbox records containing `key`, `email`, `label`, and `token_path`.

- [ ] **Step 1: Copy only non-secret source files from the reference bundle**

Run:

```bash
mkdir -p /private/tmp/gmail-multi-account-manager-build/worker
rsync -a --exclude '.venv' --exclude 'secrets' --exclude 'runtime/oauth_client.json' --exclude 'runtime/mailboxes.json' /Users/macbook/Downloads/gmail-ai-daily-ops-bundle/tools/gmail-ai-worker/ /private/tmp/gmail-multi-account-manager-build/worker/
```

Expected: staged worker contains Python source and no OAuth client or token JSON.

- [ ] **Step 2: Write failing mailbox isolation tests**

```python
def test_registers_two_accounts_with_distinct_private_tokens(tmp_path):
    registry = MailboxRegistry(tmp_path / "runtime", tmp_path / "secrets")
    first = registry.register("alpha@gmail.com", '{"refresh_token":"one"}')
    second = registry.register("beta@gmail.com", '{"refresh_token":"two"}')
    assert first["key"] != second["key"]
    assert registry.resolve(first["key"]) != registry.resolve(second["key"])
    assert registry.resolve(first["key"]).stat().st_mode & 0o777 == 0o600


def test_rejects_workspace_account(tmp_path):
    registry = MailboxRegistry(tmp_path / "runtime", tmp_path / "secrets")
    with pytest.raises(ValueError, match="personal Gmail"):
        registry.register("user@example.com", "{}")


def test_ambiguous_active_mailboxes_require_explicit_key(tmp_path):
    registry = populated_registry(tmp_path, active=["alpha", "beta"])
    with pytest.raises(ValueError, match="Specify --mailbox"):
        registry.resolve_active()
```

- [ ] **Step 3: Run tests and verify RED**

Run: `cd /private/tmp/gmail-multi-account-manager-build/worker && python3 -m pytest tests/test_mailboxes.py -v`

Expected: FAIL because the required registry constructor and registration rules do not exist.

- [ ] **Step 4: Implement mailbox isolation minimally**

Implement canonical lowercase email validation with `email.endswith("@gmail.com")`, derive a stable slug plus short SHA-256 suffix, write tokens atomically under `secrets/mailboxes/<key>.json`, set directories to `0700`, files to `0600`, and write only token paths to `runtime/mailboxes.json`.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd /private/tmp/gmail-multi-account-manager-build/worker && python3 -m pytest tests/test_mailboxes.py -v`

Expected: all mailbox tests PASS.

### Task 2: Add Safe Draft Preview and One-Draft Send Primitive

**Files:**
- Modify: `/private/tmp/gmail-multi-account-manager-build/worker/gmail_ai_worker/gmail_client.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/gmail_ai_worker/send_guard.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/scripts/preview_draft.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/scripts/send_confirmed_draft.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/tests/test_send_guard.py`

**Interfaces:**
- Produces: `DraftPreview(mailbox, draft_id, fingerprint, to, cc, bcc, subject, body, attachments)`.
- Produces: `preview_draft(service, mailbox: str, draft_id: str) -> DraftPreview`.
- Produces: `send_confirmed_draft(service, draft_id: str, expected_fingerprint: str, automation: bool) -> dict`.

- [ ] **Step 1: Write failing send-guard tests**

```python
def test_preview_contains_all_confirmation_fields(fake_service):
    preview = preview_draft(fake_service, "alpha", "draft-1")
    assert preview.mailbox == "alpha"
    assert preview.to == ["person@example.com"]
    assert preview.subject == "Status"
    assert preview.body == "Ready for review"
    assert preview.attachments == ["report.pdf"]
    assert len(preview.fingerprint) == 64


def test_changed_draft_invalidates_confirmation(fake_service):
    preview = preview_draft(fake_service, "alpha", "draft-1")
    fake_service.change_subject("draft-1", "Changed")
    with pytest.raises(ValueError, match="Draft changed"):
        send_confirmed_draft(fake_service, "draft-1", preview.fingerprint, False)


def test_automation_can_never_send(fake_service):
    preview = preview_draft(fake_service, "alpha", "draft-1")
    with pytest.raises(PermissionError, match="automation"):
        send_confirmed_draft(fake_service, "draft-1", preview.fingerprint, True)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd /private/tmp/gmail-multi-account-manager-build/worker && python3 -m pytest tests/test_send_guard.py -v`

Expected: FAIL because `send_guard` does not exist.

- [ ] **Step 3: Implement canonical preview and fingerprint**

Decode the Gmail draft MIME tree, normalize address lists, body text and attachment names, and compute SHA-256 over canonical JSON containing mailbox key, draft ID, recipients, subject, body, and attachments. Do not include OAuth data in the preview.

- [ ] **Step 4: Implement guarded sending**

Reload the draft immediately before send, recompute its fingerprint, reject automation when `CODEX_AUTOMATION=1` or `--automation` is passed, reject fingerprint mismatch, and call `users().drafts().send(userId="me", body={"id": draft_id})` exactly once.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd /private/tmp/gmail-multi-account-manager-build/worker && python3 -m pytest tests/test_send_guard.py -v`

Expected: all send-guard tests PASS.

### Task 3: Complete Multi-Mailbox CLI Coverage

**Files:**
- Modify: `/private/tmp/gmail-multi-account-manager-build/worker/scripts/connect_mailbox.py`
- Modify: `/private/tmp/gmail-multi-account-manager-build/worker/scripts/collect_thread_snapshot.py`
- Modify: `/private/tmp/gmail-multi-account-manager-build/worker/scripts/get_thread_detail.py`
- Modify: `/private/tmp/gmail-multi-account-manager-build/worker/scripts/create_reply_draft.py`
- Modify: `/private/tmp/gmail-multi-account-manager-build/worker/scripts/modify_thread.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/scripts/create_message_draft.py`
- Create: `/private/tmp/gmail-multi-account-manager-build/worker/tests/test_cli_routing.py`

**Interfaces:**
- Every mailbox-facing command consumes `--mailbox <key>`.
- Ambiguous active selection exits nonzero with `Specify --mailbox`.
- Every JSON result includes `mailbox_key` and `mailbox_email`.

- [ ] **Step 1: Write failing routing and attribution tests**

```python
def test_snapshot_attributes_each_result_to_mailbox(cli, two_mailboxes):
    result = cli("collect_thread_snapshot.py", "--mailbox", "alpha")
    assert result["mailbox_key"] == "alpha"
    assert result["mailbox_email"] == "alpha@gmail.com"


def test_command_fails_closed_when_two_mailboxes_are_active(cli, two_mailboxes):
    result = cli("collect_thread_snapshot.py", expect_failure=True)
    assert "Specify --mailbox" in result.stderr
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd /private/tmp/gmail-multi-account-manager-build/worker && python3 -m pytest tests/test_cli_routing.py -v`

Expected: attribution or ambiguity tests FAIL.

- [ ] **Step 3: Route all commands through one registry resolver**

Replace fallback-token behavior with explicit registry resolution. Permit omission only when exactly one mailbox is active. Add mailbox identity to all JSON output and verify connected profile identity before mutations.

- [ ] **Step 4: Add new-message draft creation**

Accept `--to`, optional repeated `--cc`/`--bcc`, `--subject`, and exactly one of `--body`/`--body-file`. Create a draft only; never send from this command.

- [ ] **Step 5: Run the complete worker suite**

Run: `cd /private/tmp/gmail-multi-account-manager-build/worker && python3 -m pytest -v`

Expected: all tests PASS.

### Task 4: Create and Forward-Test the Codex Skill

**Files:**
- Create: `/private/tmp/gmail-multi-account-manager-build/skill/SKILL.md`
- Create: `/private/tmp/gmail-multi-account-manager-build/skill/agents/openai.yaml`
- Create: `/private/tmp/gmail-multi-account-manager-build/skill/references/commands.md`

**Interfaces:**
- Skill triggers for Gmail, inbox, email triage, multiple Google accounts, drafts, replies, labels, archive, and sending.
- Skill invokes worker commands under `~/.codex/gmail-multi-account-manager`.

- [ ] **Step 1: Run baseline skill scenarios without the new skill**

Use fresh subagents for: “search both Gmail accounts,” “send these two drafts,” and “run this as an hourly automation.” Record whether they lose account attribution, treat batch approval as sufficient, or allow automated sending.

- [ ] **Step 2: Initialize the skill scaffold**

Run:

```bash
python3 /Users/macbook/.codex/skills/.system/skill-creator/scripts/init_skill.py gmail-multi-account-manager --path /private/tmp/gmail-multi-account-manager-build --resources references --interface display_name="Gmail Multi-Account Manager" --interface short_description="Safely manage multiple personal Gmail inboxes" --interface default_prompt="Use $gmail-multi-account-manager to review my active Gmail inboxes."
```

Expected: valid skill scaffold at `/private/tmp/gmail-multi-account-manager-build/gmail-multi-account-manager`.

- [ ] **Step 3: Write the minimal skill from baseline failures**

Specify mailbox discovery, explicit result attribution, full-thread-before-draft, canonical draft preview, one-confirmation-per-draft, changed-draft invalidation, no automation sends, destructive-operation confirmation, and secret-handling rules. Keep command syntax in `references/commands.md`.

- [ ] **Step 4: Validate the skill**

Run:

```bash
python3 /Users/macbook/.codex/skills/.system/skill-creator/scripts/quick_validate.py /private/tmp/gmail-multi-account-manager-build/gmail-multi-account-manager
```

Expected: validation succeeds.

- [ ] **Step 5: Forward-test with the skill**

Repeat the baseline scenarios in fresh subagents with the skill path supplied. Expected: account attribution is preserved, each send stops for its own confirmation, and automation creates drafts but refuses to send.

### Task 5: Install, Migrate, and Verify

**Files:**
- Create: `/Users/macbook/.codex/gmail-multi-account-manager/`
- Create: `/Users/macbook/.codex/skills/gmail-multi-account-manager/`
- Remove after validation: `/Users/macbook/.agents/skills/gws-gmail-read/`

**Interfaces:**
- Installed worker root: `/Users/macbook/.codex/gmail-multi-account-manager`.
- Installed skill root: `/Users/macbook/.codex/skills/gmail-multi-account-manager`.

- [ ] **Step 1: Install runtime without reference tokens**

Run:

```bash
rsync -a --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'tests' /private/tmp/gmail-multi-account-manager-build/worker/ /Users/macbook/.codex/gmail-multi-account-manager/
python3 -m venv /Users/macbook/.codex/gmail-multi-account-manager/.venv
/Users/macbook/.codex/gmail-multi-account-manager/.venv/bin/pip install -r /Users/macbook/.codex/gmail-multi-account-manager/requirements.txt
```

- [ ] **Step 2: Install the validated skill**

Run:

```bash
rsync -a /private/tmp/gmail-multi-account-manager-build/gmail-multi-account-manager/ /Users/macbook/.codex/skills/gmail-multi-account-manager/
```

- [ ] **Step 3: Verify installed files and permissions**

Run installed unit tests or import checks, validate the installed skill, scan for token-like strings outside `secrets`, and confirm secret directories are `0700`.

Expected: checks pass and no refresh token is found in skill or source files.

- [ ] **Step 4: Remove the old narrow skill**

Remove only `/Users/macbook/.agents/skills/gws-gmail-read` after all replacement checks pass. Preserve `/Users/macbook/.agents/skills/gws-shared` because other Google Workspace skills may depend on it.

- [ ] **Step 5: Connect and verify personal Gmail accounts interactively**

For each mailbox, run `scripts/connect_mailbox.py`, let the user select the account in the browser, then run a read-only profile and inbox smoke test with its explicit mailbox key. Finally, run a cross-mailbox read and verify every result retains its mailbox identity.

- [ ] **Step 6: Stop before live sending**

Create a designated test draft only if requested. Do not send it without a new, draft-specific user confirmation showing mailbox, recipients, subject, body, and attachments.
