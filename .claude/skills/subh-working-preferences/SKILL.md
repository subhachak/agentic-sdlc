---
name: subh-working-preferences
description: "Subh's standing preferences for how Claude should work with him: answer altitude and format, code conventions, commit message style, the agentic application stack he builds on (LangGraph, FastAPI, Pydantic, the Anthropic SDK behind a single adapter), his deployment and release posture, and toolchain defaults (uv, pytest, Next.js). Consult this at the START of any coding, debugging, review, architecture, agent-orchestration, CI, or deployment task in Subh's own work, and any time you are about to choose an orchestration framework, wire up an LLM call, design a release or rollback path, write a commit message, or decide how much explanation an answer needs. It applies even when he does not mention preferences, style, or conventions, because these are defaults he expects rather than things he restates. Not a substitute for a repository's own AGENTS.md or CLAUDE.md, which win on anything project-specific."
---

# Subh's working preferences

Standing defaults, not a checklist to recite. Apply them silently and get on
with the task.

Subh works at Mphasis on agentic SDLC tooling: platforms where agents
propose, deterministic code decides, and every decision is recorded with its
evidence. Assume he knows the stack. Skip the orientation paragraph.

## Precedence

A repository's `AGENTS.md` or `CLAUDE.md` outranks this file on anything
project-specific: invariants, layout, commands, local conventions. Read it
before changing code and follow it where the two differ. This file covers
what travels with Subh between projects.

Two sibling skills own their own domains, and this file does not restate
them:

- `mphasis-writing-voice` for prose he will send or publish
- `mphasis-deck-standards` for PowerPoint

If a task is writing or a deck, use those. The one rule worth carrying here
because it is easy to violate mid-task: **no em dashes in text drafted for
Subh to send or publish.** Restructure the sentence instead.

## Answering

Match the altitude of the question. A yes/no question gets a yes or no in
the first line, then the reasoning only if the reasoning changes what he
does next. He reads fast and asks follow-ups; a long preamble costs him more
than a missing caveat does.

Use bullets wherever there is more than one point. A list buried in a
paragraph makes him re-read it to extract the items.

When there is a real choice to make, give the tradeoff and your
recommendation. A survey of five options with no opinion pushes the work
back onto him, which is the opposite of the point.

## Scope discipline

Fix what was asked. If you notice something adjacent that is genuinely
wrong, name it in one line and let him decide. Do not fold it into the diff.

No unrequested refactors, and no reformatting of code you were not asked to
touch. A diff that mixes the fix with incidental churn is harder to review
than the two changes separately, so it costs more than it saves.

If a guard, test, or invariant is in the way, do not route around it. Either
change it deliberately and say why in the same commit, or stop and say it is
blocking. Routing around a guard is how the guard stops being true.

## Code

**Comments explain the decision, not the code.** A non-obvious block should
say what went wrong without it, in the register of:

- `the truthiness test sent refused changes onward`
- `nothing in production ever supplied one, so the check could not fire`

A comment that restates the line below it is noise. A comment that records
the failure the line prevents is the reason the line survives the next
refactor.

Match the surrounding code's idiom over any external style guide. Consistency
inside a file beats correctness against a manual nobody in the repo is
reading.

Prefer the smallest diff that makes the change true.

## Architecture

The patterns Subh reaches for, useful as defaults when a design is open:

- Ports and adapters. A deterministic core imports interface types, never
  concrete adapters; adapters are built once at the entry point and passed
  in.
- Invariants enforced by a test rather than by convention. A rule that only
  lives in a document is a rule that has already drifted.
- Number the invariants so a review can cite them.

Do not impose these on a codebase that has chosen differently. They are what
to reach for on a blank page. For agentic systems specifically, the stack
section below carries the rest.

## Toolchain

- Python 3.11+, `uv` for everything: `uv run pytest -q`, `uv run python ...`.
  Never `pip install` into an ambient environment.
- Web: Next.js, React, TypeScript, npm scripts.
- Check for a `Makefile` before inventing a command. Most of his repos expose
  the real entry points there.
- Run the project's own tests and linters before saying something works. If
  you did not run them, say so plainly rather than implying verification.

## Agentic application stack

What Subh builds on, and the shape these systems take. Defaults for a new
agentic service, not a mandate for an existing one.

- **Orchestration: LangGraph.** Graph nodes for phases, a checkpointer for
  durable state, `interrupt()` for anything that waits on a human or a
  remote job. Keep `interrupt()` to one call site; a pause for a person and
  a pause for a remote job are the same mechanism with different resumers.
  LangGraph re-runs a node from its top on resume, so everything before the
  interrupt executes twice. Guard writes with a dedupe flag and side effects
  with a uniqueness constraint, or the second pass fires the dispatch again.
- **API: FastAPI**, Pydantic v2 models, `pydantic-settings` for config, SSE
  via `sse-starlette` when the client needs to watch a run.
- **Persistence: SQLAlchemy 2.x async.** SQLite through `aiosqlite` is a
  legitimate production choice for a single-writer control plane, not a
  placeholder to apologize for.
- **Models: the `anthropic` SDK, confined to one adapter module.** No other
  module imports it, directly or transitively. Enforce it with a test that
  imports each module in a clean subprocess, and keep adapter imports lazy
  inside their factory branches so the registry does not drag the SDK into
  everything that touches it.
- **QA execution: Playwright specs**, generated by an agent and executed
  somewhere that holds no write token.

The architectural rule underneath all of it: **agents propose, deterministic
code decides.** An agent may draft a plan, a design, a change, or a test.
Only plain code may accept one. Never let a gate's outcome depend on model
output, and never import the LLM module into a gate.

Two habits that follow from it:

- Every port gets a factory in the adapter registry, and a `mock` adapter
  selected by env var. A pipeline that cannot run end to end with no
  credentials and no network cannot be demonstrated on a laptop or tested in
  CI, and both matter more than they sound.
- Text-scanning agent-authored code before running it is defense in depth,
  not a sandbox. The real control is the privilege split: the job that
  executes generated code holds `contents: read` and nothing else, the job
  that writes results executes none of that code, and they communicate
  through a serialized state file. Never merge those jobs to simplify a
  workflow.

## Deployment and release

Subh's posture is that a platform should drive the client's existing
machinery rather than replace it. The point of a demo is showing the
controls working, not routing around them.

- **Release by merging the approved pull request**, and let whatever the
  client already has react to it: Vercel, Railway, their own pipeline. Do
  not call a hosting provider's API to push a deploy. Nothing should bypass
  their CI or their branch protections.
- **Pin the approved sha at merge.** A commit landed between approval and
  release would otherwise ride along, and the audit trail would then name a
  revision nobody reviewed.
- **Rollback is a git revert**, through the same door. A forward-only
  deployment path is a defect, not a phase-two feature. If a system can
  release, it must be able to withdraw the release, and withdrawing it means
  withdrawing the claim in the audit trail as well as the code.
- **Never report health you did not observe.** When a merge succeeds and the
  deploy it triggers takes minutes, health is unknown, not healthy. Model it
  as nullable and pass the unknown through. An adapter inventing `True`
  because it has no integration is worse than one admitting it cannot tell.
- **Observe through a signal every host reports to**, such as GitHub
  deployment statuses, rather than one provider's API. One credential covers
  every host, and no host gets silently assumed green for want of an
  integration. Every host has to be green: one green and one red is half a
  release, which is the state rollback exists for.
- **A release says whether it worked**, not merely that it happened.

CI conventions: pin `runs-on` and a `timeout-minutes` on every job, set
`permissions` explicitly and minimally per job, add a `concurrency` group
wherever two runs could race on a shared store or both post to the same pull
request, and scope `paths` so a workflow only fires on changes that can
affect what it asserts.

## Git

Commit subjects state what is now true, rather than instructing the reader.
Format is `type: lowercase claim`, with `feat`, `fix`, or `docs`:

- `fix: generated specs no longer run with the caller's credentials`
- `feat: a release says whether it worked, not only that it happened`
- `feat: debt is declared, and the declaration may not grow`

Not `Fix credentials bug` or `Add release status`. The subject reads as a
statement about the system after the change, which is what makes the log
scannable as a history of behavior instead of a list of activities.

The body explains why, and cites the invariant or test when one is involved.

Other standing rules:

- Never push to `main`. Branch first.
- Never rewrite history on a branch that is not his.
- Keep model names and assistant identifiers out of commits, PR bodies, and
  code comments.
