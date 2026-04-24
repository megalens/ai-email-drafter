# Case Study: Building an AI Email Drafter with Claude Code + MegaLens MCP

## The short version

I built a tool that reads your Gmail inbox and writes draft replies for you, answered only from a file you control. Claude Code wrote the plan and the code. MegaLens MCP reviewed the plan before I started coding, and reviewed every commit during the build.

The plan review caught 15 problems before a single line of code existed. Two of those were serious enough that they would have caused real trouble in production. 13 of the 15 were things I hadn't spotted in my own review.

The whole build was recorded live. The repo is public. Nothing was staged.

---

## What I built (and why)

**The problem:** If you run a service business, you get a lot of email. Some of it is real business inquiries. Most of it is newsletters, auto-replies, and noise. Identifying the real ones and writing back takes time. And you keep writing the same answers to the same questions.

**The solution:** An AI Email Drafter. A tool that:

1. Watches your Gmail inbox
2. Filters out the noise automatically (no AI needed for this part, just rules)
3. For real business emails, checks: "Can I answer this from the information the user gave me?"
4. If yes, writes a draft reply in your Gmail Drafts folder
5. If no, does nothing. No guessing, no making things up.

You open Gmail, see the drafts, review them, tweak if needed, and send yourself. The tool never sends anything on your behalf. It can't. It doesn't even have permission to send.

**The "context file":** You write a simple text file (`context.md`) with your business info, FAQs, service descriptions, and tone preferences. The tool only answers from this file. If someone asks about something not in the file, it skips. This is the safety net that prevents the AI from inventing answers.

---

## How I built it

### The tools

| Tool | Role |
|---|---|
| **Claude Code** | Wrote the build plan. Wrote all the code. Ran tests. Made commits. |
| **MegaLens MCP** | Reviewed the plan before coding started. Reviewed each commit during the build. Caught blind spots. |

Think of it like this: Claude Code is the builder. MegaLens is the inspector who walks through the building plans and then checks each floor as it goes up.

### Why use an inspector?

When one AI writes a plan and then reviews its own plan, it tends to agree with itself. The same patterns it used to write the plan are the same ones it uses to evaluate it. Blind spots stay blind.

MegaLens routes your review to multiple specialist AI engines. They review independently. They disagree with each other. That disagreement is where you find the gaps that a single reviewer misses.

I didn't use MegaLens to prove the plan was correct. I used it to catch things I would have missed.

---

## What happened: the plan review

### Before MegaLens

I wrote a detailed build plan with Claude Code. 19 sections covering everything: how the tool works, how emails get filtered, how the AI decides what to draft, how credentials are stored, how to deploy it, how to test it.

Then I did my own review. Quick pass. I found 2 things worth flagging.

### After MegaLens

I ran MegaLens on the full plan. It came back with 15 findings.

Here's the breakdown:

| Severity | Count | What it means |
|---|---|---|
| Critical | 2 | Would have caused real damage in production |
| High | 7 | Would have caused problems within the first month of use |
| Medium | 6 | Would have caused friction but probably not incidents |

### The critical ones (in plain terms)

**1. The cost limit was fake.**

The plan had a daily spending cap ($5/day) to prevent runaway AI costs. Sounds good. But there was no code to actually check how much each AI call cost. The plan said "track costs" but never specified where the cost number comes from. The cap was a sign on the wall that nobody reads.

**Fix:** Added actual cost calculation from every API response. The tool now parses the real token usage (input, output, cached) and multiplies by per-model rates. The circuit breaker checks this running total before every AI call.

**2. Fresh install would flood your inbox with drafts.**

If the tool's database got deleted (or on first install), the plan said: fetch all unread emails. On a busy inbox, that could mean hundreds of old emails. Each one gets processed. Each one might generate a draft. Surprise: 50 unwanted drafts and a $20 API bill.

**Fix:** Added a time limit. On fresh install, the tool only looks at the last 1 day of email (configurable). Old mail is ignored.

### Some of the high-severity ones

- **Prompt injection through email headers.** The email body was treated as untrusted (good), but the Subject line and From address were passed straight into the AI prompt without cleaning. An attacker could craft a Subject line that manipulates the AI. Fix: all headers now get sanitized (control characters stripped, truncated, newlines removed).

- **Duplicate drafts on crash.** If the tool decided to create a draft but crashed before saving it, on restart it would create the same draft again. Fix: record the intent in the database before creating the draft.

- **Poison messages retry forever.** If a specific email consistently causes errors (malformed content, encoding issues), the tool would keep retrying it every poll cycle, forever. Fix: after 3 failures, the message is quarantined and stops retrying.

---

## The build: 12 steps, each reviewed

After fixing all 15 findings in the plan, I built the tool in 12 steps:

1. Project setup + config loading
2. Database with encrypted credential storage
3. Gmail integration (OAuth, read inbox, save drafts)
4. Email filter (8 rules to catch noise without AI)
5. Context file loader with auto-reload
6. AI classifier and draft writer
7. Pipeline connecting all pieces
8. Polling loop with incremental sync
9. Cost tracking and daily cap
10. Deployment setup (systemd service)
11. End-to-end test suite
12. Adversarial prompt injection tests

Each step: write code, test, commit, review with MegaLens, fix if needed, then move on.

---

## The final product

| What | Details |
|---|---|
| Language | Python |
| AI model | Claude Sonnet 4.6 (via Anthropic API) |
| Email provider | Gmail (read + draft only, no send permission) |
| Tests | 350+, including 10+ prompt injection attacks |
| Deployment | systemd service on any Linux server |
| Config | TOML file + environment variables for secrets |

The tool runs quietly in the background. When it finds an email worth answering, you see a new draft in Gmail. If it can't answer from your context file, it does nothing. No notification, no error, just a skip.

---

## Safety choices I made

These aren't features. They're constraints. I deliberately limited what the tool can do.

1. **It can't send email.** Not "it doesn't send." It _can't_. The Gmail permission it requests (gmail.compose) only allows creating drafts. The send permission (gmail.send) is never requested. Even if the code had a bug, it couldn't send.

2. **It only answers from your file.** The AI sees your context file and the incoming email. If the answer isn't derivable from your file, no draft. No "let me check and get back to you." No "based on what I know." Just nothing.

3. **Old email is ignored on fresh start.** The tool only processes recent email on first run (default: last 24 hours). It won't surprise you with 200 drafts from last month.

4. **Bad messages stop retrying.** If a specific email crashes the tool 3 times, it gets quarantined. The tool moves on.

5. **Your credentials are encrypted.** Gmail tokens are encrypted on disk. API keys live in environment variables, never in config files.

---

## What I would improve

- **Verify draft claims against the context file.** Right now, the "only answer from context.md" rule is enforced by telling the AI to follow it. A code-based verification step that checks every claim in the draft against the actual file would be stronger.
- **Support Outlook.** Gmail-only is a real limitation. Microsoft Graph API integration would open this up to a much larger user base.
- **Learn from edits.** When you consistently change how drafts are worded, the tool could suggest updates to your context file. No learning loop exists today.
- **Multi-language support.** V1 is English-only.

---

## Honest notes

I want to be clear about what this case study shows and what it doesn't.

**What it shows:** MegaLens caught real gaps in a real plan. The workflow (plan review before coding, per-commit review during coding) produced a more thorough result than coding straight from the plan would have.

**What it doesn't show:**
- My pre-audit was intentionally quick (a few items per category). A more careful self-review would have caught more than 2 of the 15.
- Some findings would probably have surfaced during implementation even without MegaLens.
- MegaLens produces findings, not proofs. Every finding required my judgment to assess and fix.
- This is one build. Your mileage will vary depending on the project, the plan quality, and how thorough your own review process is.

This is a live build and case study. Not a polished benchmark.

---

## Links

| Resource | Link |
|---|---|
| GitHub repo | [github.com/megalens/ai-email-drafter](https://github.com/megalens/ai-email-drafter) |
| Build video | <!-- VIDEO_URL --> |
| Safety model | [docs/SAFETY_MODEL.md](SAFETY_MODEL.md) |
| MegaLens workflow | [docs/MEGALENS_WORKFLOW.md](MEGALENS_WORKFLOW.md) |
| MegaLens | [megalens.ai](https://megalens.ai) |
