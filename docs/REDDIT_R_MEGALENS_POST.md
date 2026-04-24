# Reddit Post Draft: r/Megalens

## Title options

1. "Built an AI Email Drafter with Claude Code. MegaLens caught 15 gaps in the plan before I wrote any code."
2. "Live build session: AI Email Drafter, Claude Code + MegaLens MCP. 13 of 15 findings were things I missed."
3. "Plan audit before coding: MegaLens caught 2 critical gaps, 7 high, 6 medium. Full repo + recording."

**Recommended:** Option 1. Clear, specific, no hype.

---

## Post body

Built an AI email drafter this week. It's a self-hosted tool that polls Gmail, identifies business emails, and creates draft replies answered only from a context file you write. Never sends. Drafts only. If the answer isn't in your file, no draft gets created.

Used Claude Code as the coding tool and MegaLens MCP as the review layer.

---

### The build

| Step | What happened |
|---|---|
| Plan | Wrote a 19-section build plan with Claude (architecture, data model, security, prompts, testing) |
| Pre-audit | Did my own quick review. Found 2 items. |
| MegaLens audit | Ran MegaLens on the plan before writing code. Got 15 findings. |
| Fix | Fixed all 15 in the plan. |
| Build | 12 implementation steps, each commit reviewed by MegaLens before proceeding. |
| Result | Working service. 350+ tests. Adversarial prompt injection suite. |

---

### What MegaLens caught (that I missed)

13 of the 15 findings were additions beyond my own pre-audit. Some highlights:

**Critical:**
- Cost cap was decorative. The plan had a daily USD cap but no code to parse actual costs from the API response. Without usage parsing, the cap does nothing.
- Bootstrap re-drafting. On database loss, the tool would process every unread email in the inbox, not just recent ones. Surprise API bill and dozens of unwanted drafts.

**High:**
- Email headers passed raw into the LLM prompt. An attacker could inject prompt content through a crafted Subject line.
- Draft-create race condition. If the service crashed between deciding to draft and saving the draft, it would create a duplicate on restart.
- No MIME parsing spec. The plan said "extract email body" but didn't specify how to handle multipart, HTML fallback, charset detection, or signature stripping.
- Poison messages would retry forever. No quarantine, no backoff limit.

---

### Safety model

Two hard defaults:

1. **Draft, never send.** Gmail send scope is not requested. The tool can't send email.
2. **Skip, never hallucinate.** If the context file doesn't answer the question, no draft. No guessing, no "I'll get back to you."

Email bodies treated as untrusted. Headers sanitized before LLM. Structured JSON output. Encrypted tokens at rest.

Full safety model in the repo.

---

### Honest notes

This is a live build and case study, not a polished benchmark.

- My pre-audit was deliberately quick. A thorough self-review would have caught more than 2 of the 15.
- Some findings might have surfaced during implementation anyway. Others probably wouldn't have until production.
- MegaLens produces findings, not proofs. Every finding needed human judgment to assess and fix.
- This is one build on one plan. Your results will vary.

---

### Links

| | |
|---|---|
| Repo | [github.com/megalens/ai-email-drafter](https://github.com/megalens/ai-email-drafter) |
| Build video | https://youtu.be/czGDhTi7Lb4 |
| Case study | https://github.com/megalens/ai-email-drafter/blob/master/docs/CASE_STUDY.md |
| Safety model | In repo at `docs/SAFETY_MODEL.md` |
| MegaLens | [megalens.ai](https://megalens.ai) |
