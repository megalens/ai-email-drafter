# MegaLens MCP Workflow: How It Supported This Build

This document explains, technically, how MegaLens MCP was used during the AI Email Drafter build.

---

## What MegaLens MCP is

MegaLens is an MCP (Model Context Protocol) server that provides structured multi-engine AI review from inside your IDE. Instead of asking one model to review code or a plan, MegaLens routes the review to multiple specialist AI engines, collects their findings independently, and returns structured results.

It works as an MCP tool inside Claude Code, Codex CLI, or Gemini CLI. You call it like any other MCP tool. Your IDE stays the final decision-maker. MegaLens provides the findings. You (and your IDE) decide what matters.

---

## How it was used in this build

### Pre-implementation: plan audit

The full build plan (19 sections, covering architecture, data model, security, prompt design, deployment, and testing) was sent to MegaLens through the `megalens_debate` MCP tool.

MegaLens routed the plan to its specialist engines. Each engine reviewed independently across four categories:
- Security gaps
- Operational gaps
- Design gaps
- Scope discipline

The engines produced findings. MegaLens structured those findings and returned them. I compared against my own pre-audit to see what was new.

**Result:** 15 findings total. 13 were additions beyond my pre-audit. All 15 were accepted and fixed in the plan before implementation started.

### During implementation: per-commit review

Each of the 12 implementation steps followed the same cycle:

1. Write the code, run tests, commit
2. Run my own pre-audit on the commit diff (max 2 items per category: correctness, security, design)
3. Run MegaLens on the single commit through `megalens_debate`
4. Compare MegaLens findings against my pre-audit
5. Fix issues in a follow-up commit if needed

The per-commit granularity matters. Reviewing a single step's diff is more focused than reviewing the entire codebase at the end. Both MegaLens and my own review are more useful when the scope is narrow.

---

## What MegaLens added to the workflow

### Structured disagreement

The value isn't "more AI opinions." It's structured disagreement. When multiple engines review the same artifact:

- Some findings appear from all engines (consensus). These are usually real.
- Some findings appear from one engine only (divergence). These are where blind spots get caught.
- Some findings contradict each other. This forces you to think instead of rubber-stamping.

A single-model review tends to produce a consistent view. MegaLens produces a view with visible tensions. That's harder to work with but more useful.

### Reduced back-and-forth

Without MegaLens, the review cycle is: write code, ask Claude to review, get findings, ask Claude to fix, repeat. The problem is that Claude reviewing Claude's code has correlated blind spots.

With MegaLens: write code, run MegaLens, get independent findings from multiple engines, fix in one pass. The findings come from outside Claude's review pattern, so they're more likely to catch things Claude wouldn't flag on self-review.

### Pre-code review

The most valuable use in this build was the plan audit before any code was written. Catching "cost cap is unenforceable" at the plan stage costs a paragraph edit. Catching it at the implementation stage costs a refactor. Catching it in production costs money and trust.

---

## What MegaLens did NOT do

- **Did not write code.** All code was written by Claude Code.
- **Did not make decisions.** All decisions about which findings to accept, reject, or defer were mine.
- **Did not prove correctness.** It produces findings, not proofs. Findings require human judgment.
- **Did not replace testing.** The 350+ test suite and adversarial prompt injection tests exist because review catches design issues, not implementation bugs. Tests catch implementation bugs.
- **Did not guarantee completeness.** 15 findings on the plan doesn't mean there are exactly 15 gaps. Some gaps won't be found by any review tool.

---

## Cost

The plan audit ran at Standard tier. Per-commit reviews were lighter. Total MegaLens cost for the entire build was under $2.

---

## When this workflow makes sense

This workflow (plan audit + per-commit review) works well when:

- The project has a clear plan document before implementation
- Implementation is broken into discrete, reviewable steps
- The codebase touches security-sensitive areas (OAuth, prompt injection, credential storage)
- You want independent review but don't have a second human reviewer available

It's less useful for:
- Quick scripts or throwaway code
- Purely mechanical changes (renames, formatting)
- Codebases where the plan is "figure it out as we go"
