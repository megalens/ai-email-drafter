# AI Email Drafter

A self-hosted tool that reads your Gmail inbox, identifies emails that look like real business opportunities, and creates draft replies — answered only from a context file you write and control.

You review every draft. You send every reply. The tool never sends anything on your behalf.

**Built with [Claude Code](https://claude.ai/code). Reviewed with [MegaLens MCP](https://megalens.ai).**

| | |
|---|---|
| Build video | [Watch the build session](<!-- VIDEO_URL -->) |
| Case study | [How MegaLens reviewed the build](docs/CASE_STUDY.md) |
| Safety model | [docs/SAFETY_MODEL.md](docs/SAFETY_MODEL.md) |

---

## What it does

1. Polls your Gmail inbox on a schedule (default: every 5 minutes)
2. Filters out noise — newsletters, auto-replies, notifications, internal emails — using 8 hard rules, no LLM needed
3. For emails that pass the filter, asks Claude whether the question is answerable from your `context.md`
4. If yes, creates a draft reply in your Gmail Drafts folder
5. If no, skips silently — no draft, no hallucination, no guessing

You open Gmail, see the drafts, review them, edit if needed, and hit send yourself.

---

## Features

- **Draft only, never send.** Gmail send scope is never requested. The tool physically cannot send email.
- **Closed-world answers.** Every claim in a draft traces back to your `context.md`. If the answer isn't there, no draft is created.
- **Prompt injection defense.** Email bodies are treated as untrusted quoted data. Headers are sanitized. The LLM is instructed to ignore in-body instructions.
- **Cost controls.** Daily USD cap with circuit breaker. Actual cost tracked per-message from API response usage, not estimated.
- **Encrypted token storage.** Gmail OAuth tokens encrypted at rest with Fernet. API keys in env vars, never in config files.
- **Poison message quarantine.** Messages that fail 3 times are quarantined and stop retrying.
- **Hot reload.** Update `context.md` while the service is running. Changes picked up on the next poll cycle, no restart needed.
- **Prompt caching.** Your `context.md` is cached in the Anthropic API for 5 minutes, cutting cost by ~90% on subsequent emails in the same cycle.

---

## Safety model

See [docs/SAFETY_MODEL.md](docs/SAFETY_MODEL.md) for the full safety model.

Summary of the two core defaults:

1. **Draft, never send.** Every output is a Gmail Draft. No auto-send, no whitelist bypass, no exceptions.
2. **Skip, never hallucinate.** If `context.md` doesn't answer the question, the tool returns SKIP and creates no draft.

These defaults eliminate the two catastrophic failure modes: sending a wrong reply, and inventing a plausible-sounding wrong answer.

---

## Architecture

```
Gmail Inbox
    | (poll every N minutes)
Fetch new messages since last checkpoint
    |
[Layer 1: Rule-based pre-filter]  (8 hard rules, no LLM)
    |--- noreply/auto-reply sender detection
    |--- auto-generated email headers
    |--- internal domain filter
    |--- already-replied / draft-exists check
    |--- SPAM/TRASH/SENT label exclusion
    |--- auto-subject detection (OOF, delivery status)
    | (passes filter)
[Layer 2+3: LLM pass]  (Claude via Anthropic API)
    |--- Input: context.md + email thread + system prompt
    |--- Output: { decision: DRAFT|SKIP, reason, draft_body }
    |--- Prompt caching: context.md cached (5-min TTL)
    | (decision = DRAFT)
Save Gmail Draft in thread
    |
Update local state (SQLite)
```

### Components

| Component | File | Job |
|---|---|---|
| Config loader | `src/ai_drafter/config.py` | TOML + env vars, secret masking |
| State store | `src/ai_drafter/state.py` | SQLite with WAL, Fernet-encrypted tokens, retry tracking |
| Gmail provider | `src/ai_drafter/gmail.py` | OAuth flow, fetch, draft creation, MIME parsing |
| Layer 1 filter | `src/ai_drafter/filter.py` | 8 hard rules, no LLM call |
| Context loader | `src/ai_drafter/context.py` | File-watch reload via mtime |
| LLM drafter | `src/ai_drafter/llm.py` | Anthropic SDK, prompt caching, structured JSON output |
| Pipeline runner | `src/ai_drafter/pipeline.py` | Orchestrates filter + LLM + draft saving |
| Poller | `src/ai_drafter/poller.py` | History-based incremental fetch + bootstrap fallback |
| Service | `src/ai_drafter/service.py` | Entry point, argument parsing, component wiring |

---

## Setup

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An Anthropic API key
- A Google Cloud project with Gmail API enabled

### 1. Clone and install

```bash
git clone https://github.com/megalens/ai-email-drafter.git
cd ai-email-drafter
uv sync
```

### 2. Google Cloud OAuth setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Enable the **Gmail API**
4. Go to **APIs & Services > OAuth consent screen**
   - Choose **External** user type
   - Add your email as a test user
5. Go to **APIs & Services > Credentials**
   - Create **OAuth client ID** (Desktop application type)
   - Download the JSON file
   - Save it somewhere safe (e.g., `~/.config/ai-drafter/oauth_credentials.json`)

**Scopes requested:**
- `gmail.readonly` — read inbox and threads
- `gmail.compose` — create drafts (does NOT include send)

**Scopes NOT requested:** `gmail.send`, `gmail.modify`. The tool cannot send email.

### 3. Generate encryption key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save the output. This encrypts your Gmail OAuth tokens at rest in the SQLite database.

### 4. Create secrets file

```bash
mkdir -p /etc/ai-drafter
cat > /etc/ai-drafter/secrets.env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-your-key-here
STATE_ENCRYPTION_KEY=your-fernet-key-here
GOOGLE_OAUTH_CLIENT_SECRETS=/path/to/your/oauth_credentials.json
EOF
chmod 600 /etc/ai-drafter/secrets.env
```

### 5. Create config

```bash
cp config.example.toml /etc/ai-drafter/config.toml
```

Edit `/etc/ai-drafter/config.toml` to adjust poll interval, cost cap, and file paths.

### 6. Write your context.md

See [How to create context.md](#how-to-create-contextmd) below.

### 7. Run

```bash
# Source secrets and run directly
source /etc/ai-drafter/secrets.env
uv run ai-drafter -c /etc/ai-drafter/config.toml
```

On first run, a browser window opens for Gmail OAuth consent. Authorize the app, and the service starts polling.

### 8. (Optional) Install as systemd service

```bash
sudo bash deploy/install.sh
sudo systemctl enable ai-drafter
sudo systemctl start ai-drafter
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `STATE_ENCRYPTION_KEY` | Yes | Fernet key for encrypting OAuth tokens at rest |
| `GOOGLE_OAUTH_CLIENT_SECRETS` | Yes | Path to Google OAuth client credentials JSON file |

All secrets are loaded from environment variables, never from config files or code.

---

## How to create context.md

`context.md` is the single file the drafter answers from. If a question isn't answerable from this file, no draft is created.

### Structure

```markdown
# About
Who your business is, what you do, who you serve. 1-3 paragraphs.

# Services
- Service 1 — short description
- Service 2 — short description

# FAQs
## What is your turnaround time?
We typically deliver within 5 business days.

## Do you offer refunds?
Yes, within 14 days of delivery if requirements were not met.

# Tone
Friendly, direct, no jargon. Sign off with first name only.

# Out-of-scope
- Legal advice
- Medical advice
- Pricing not listed on our website
- Anything not covered in this file
```

### Tips

- Write FAQs as real questions your customers actually ask, not marketing copy
- The Out-of-scope section is your safety net. Anything listed here, the drafter will skip.
- Update this file any time you notice the drafter skipping emails it should answer. The service picks up changes automatically.
- Review AI-generated context carefully before first run. AI-generated FAQs can invent services you don't offer.

See [context.example.md](context.example.md) for a working example.

---

## Configuration

`config.example.toml`:

```toml
[service]
poll_interval_minutes = 5
context_file = "/etc/ai-drafter/context.md"
state_db = "/var/lib/ai-drafter/state.sqlite"

[llm]
model = "claude-sonnet-4-6"
max_context_tokens = 25000
daily_cost_cap_usd = 5.0

[gmail]
poll_max_messages = 50
bootstrap_lookback_days = 1

[logging]
level = "INFO"
file = "/var/log/ai-drafter/service.log"
max_bytes = 10485760
backup_count = 5
```

---

## Limitations

- **Gmail only.** Outlook, IMAP, ProtonMail are not supported in V1.
- **English only.** No multi-language detection or generation.
- **Single-tenant.** Designed for one user on one machine, not multi-user SaaS.
- **No attachments.** Drafts are plain text only.
- **No learning loop.** The tool does not learn from your edits to drafts.
- **No UI.** CLI and systemd service only. No web dashboard, no Gmail add-on.
- **Public pages only for bootstrap.** The `--from-url` init mode only crawls public pages, no authenticated content.

---

## Roadmap

| Version | Scope |
|---|---|
| **V1 (current)** | Gmail + context.md + drafts, single-tenant, Python CLI/daemon |
| V2 | Outlook (MS Graph), partial-match handling, CSV data source |
| V3 | Universal IMAP/SMTP, database connectors (Postgres/MySQL read-only) |
| V4 | ProtonMail Bridge, Gmail Add-on (sidebar UI) |
| V5 | Multi-tenant SaaS, Stripe billing, learning loop from user draft edits |

---

## Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test module
uv run pytest tests/test_filter.py

# Lint
uv run ruff check src/ tests/
```

The test suite includes:
- Unit tests for all components (~350 tests)
- E2E test harness with realistic email fixtures
- Adversarial prompt injection test suite (10+ attack payloads)
- MIME boundary and header injection tests

---

## How it was built

This project was built with Claude Code as the coding tool, and [MegaLens MCP](https://megalens.ai) as the review layer.

Before any code was written, the full build plan was audited through MegaLens. The audit surfaced 15 findings (2 critical, 7 high, 6 medium) that were fixed in the plan before implementation started. During implementation, each commit was reviewed through MegaLens before proceeding to the next step.

See [docs/CASE_STUDY.md](docs/CASE_STUDY.md) for the full build story.
See [docs/MEGALENS_WORKFLOW.md](docs/MEGALENS_WORKFLOW.md) for the technical workflow.

---

## Disclaimer

This tool creates Gmail drafts. It does not send email. Every draft requires manual review and manual sending by the user. The tool's outputs are AI-generated and may contain errors. Always review drafts before sending.

The tool answers only from your `context.md` file. If your `context.md` contains incorrect information, drafts will contain incorrect information. You are responsible for the accuracy of your context file and for reviewing every draft before sending.

---

## License

<!-- LICENSE_PLACEHOLDER -->
