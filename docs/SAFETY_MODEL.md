# Safety Model

This document describes the safety design of the AI Email Drafter. It covers what the tool can and cannot do, how it handles adversarial input, and where the human stays in the loop.

---

## Two core defaults

### 1. Draft, never send

Every output is a Gmail Draft. The user opens Gmail, reviews the draft, edits it if needed, and sends it manually.

The tool does not request the `gmail.send` OAuth scope. It physically cannot send email through the Gmail API. There is no auto-send feature, no whitelist bypass, no "trusted sender" mode, and no configuration option that changes this.

If the tool crashes, the worst outcome is a missing draft. Never an unsolicited reply.

### 2. Skip, never hallucinate

If the email's question is not answerable from the user's `context.md` file, the tool returns SKIP and creates no draft. The Drafts folder stays clean.

The tool operates in strict closed-world mode. Every claim in a draft must trace back to a specific section of `context.md`. The LLM is instructed: if the answer isn't there, do not guess, do not apologize, do not promise to follow up. Just skip.

---

## Prompt injection defense

Inbound emails are untrusted. Attackers can craft emails designed to manipulate the LLM.

### How the tool handles this

- **Email body isolation.** The email body is wrapped as "untrusted quoted data" in the prompt. The system prompt explicitly instructs the LLM to ignore any instructions, commands, or directives written inside the email body.

- **Header sanitization.** All email headers (From, To, Subject, Date) are sanitized before being included in the prompt:
  - Control characters and null bytes stripped
  - Newlines replaced (prevents header injection into prompt structure)
  - Truncated to 500 characters maximum
  - Encoded as UTF-8 with lossy replacement for undecodable bytes

- **Body sanitization.** Email body text has control characters removed before being sent to the LLM.

- **Structured JSON output.** The LLM returns structured JSON (`{ decision, reason, draft_body }`), not free text. This limits the attack surface for prompt injection that tries to alter the output format.

- **Closed-world constraint.** Even if prompt injection succeeds in making the LLM want to draft a reply, the closed-world rule means the draft can only contain information from `context.md`. The attacker cannot inject arbitrary content into drafts.

### What this does NOT guarantee

- Prompt injection defense is probabilistic, not provable. A sufficiently novel attack could bypass the defenses.
- The closed-world constraint is enforced by the LLM following instructions, not by code verification. There is no post-generation fact-check against `context.md`.
- If `context.md` itself contains incorrect information, drafts will contain incorrect information. The tool trusts `context.md` completely.

---

## OAuth scope minimization

The tool requests exactly two Gmail scopes:

| Scope | Permission | Why |
|---|---|---|
| `gmail.readonly` | Read inbox and threads | Fetch new inbound emails |
| `gmail.compose` | Create drafts | Save draft replies |

**Not requested:**
- `gmail.send` — the tool cannot send email
- `gmail.modify` — the tool cannot move, label, or delete messages
- `gmail.metadata` — not needed; readonly covers it

Principle of least privilege. If the OAuth token is compromised, the attacker can read email and create drafts, but cannot send from the user's account.

---

## Token encryption

Gmail OAuth tokens (access token and refresh token) are encrypted at rest in the SQLite database using Fernet symmetric encryption. The encryption key is stored in an environment variable (`STATE_ENCRYPTION_KEY`), never in config files or code.

---

## Cost controls

- **Daily USD cap.** Configurable maximum daily LLM spend (default: $5/day). The circuit breaker checks the running total before each LLM call.
- **Actual cost tracking.** Cost is calculated from the API response's `usage` object (input tokens, output tokens, cache read tokens), not estimated. Per-model rates are hardcoded.
- **Circuit breaker.** When the daily cap is exceeded, the poller pauses until the next UTC day boundary. An audit log entry is written.

---

## Failure handling

- **Poison message quarantine.** If a message fails processing 3 times (malformed email, LLM error, draft save failure), it is marked `quarantined` and stops retrying. The user can inspect quarantined messages via the SQLite database.
- **Idempotent processing.** The `processed_messages` table uses the Gmail message ID as primary key. A message is never processed twice, even after a crash and restart.
- **Bootstrap time-bounding.** On first run (or after database loss), the tool only processes emails from the last N days (configurable, default: 1 day). It does not re-draft your entire inbox history.

---

## What the tool does NOT do

- Does not send email
- Does not delete, move, or label messages
- Does not modify your inbox in any way
- Does not store email content persistently (only message IDs and processing status)
- Does not learn from your edits to drafts
- Does not phone home or share data with third parties (all processing is local + Anthropic API)
- Does not auto-respond to auto-replies (Layer 1 filter catches these)

---

## User responsibilities

- **Review every draft before sending.** Drafts are AI-generated and may contain errors.
- **Keep `context.md` accurate.** The tool trusts this file completely. If it says something wrong, drafts will say something wrong.
- **Protect your secrets.** The `secrets.env` file, encryption key, and OAuth credentials should have restrictive file permissions (0600).
- **Monitor costs.** The daily cap is a safety net, not a budget tool. Check the audit log periodically.

---

## Threat model summary

| Threat | Mitigation | Residual risk |
|---|---|---|
| Tool sends wrong reply | Draft-only, user reviews | User sends without reading |
| LLM hallucinates an answer | Closed-world, skip if not in context.md | LLM ignores instruction (probabilistic) |
| Prompt injection via email | Body isolation, header sanitization, structured output | Novel attack bypasses defenses |
| OAuth token theft | Encrypted at rest, env var secrets | VPS compromise exposes decryption key |
| Runaway LLM cost | Daily cap, circuit breaker | Cap checked per-call, not per-token |
| Inbox flooding with drafts | Bootstrap lookback limit, duplicate draft check | Misconfigured lookback window |
| Poison email crashes service | 3-retry quarantine, idempotent processing | Quarantine requires manual review |
