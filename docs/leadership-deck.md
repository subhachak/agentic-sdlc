# Agentic SDLC Platform — Leadership Briefing

> **For a PowerPoint generator.** Each `---` starts a new slide. `#` is the slide
> title, `##` a subtitle where one is wanted. Bullets are bullets. Blocks marked
> `**Notes:**` are speaker notes, not slide content. Tables should render as
> tables. Keep the slide count as written — 18 slides, roughly 25 minutes with
> questions.
>
> Audience: engineering leadership and the executive sponsor. They care about
> whether this is real, whether it is safe, whether it fits a client, and what
> it needs next. They do not care about class names.

---

# Agentic SDLC Platform

## Agents write the software. The platform proves it is safe to ship.

**Notes:** Open with the one-sentence version and stop talking. Do not start
with architecture — start with the problem on the next slide. If someone asks
"is this real" in the first minute, jump straight to slide 5 and come back.

---

# The problem is not capability

- Agents can already write requirements, design notes, code and tests
- Every large enterprise has run a pilot; almost none have put one in the
  delivery path
- The blocker is **accountability**, not intelligence

> After the fact, nobody can say who decided what, on what evidence, and
> whether a person was involved.

**Notes:** This is the whole pitch. In insurance and financial services the
question in the room is never "can the agent write the code". It is "what do I
tell the regulator". Everything we built is an answer to that second question.

---

# Our answer, in one line

## Agents propose. Deterministic code decides. Humans approve what carries risk.

- Every gate in the pipeline is plain code with **no model in it**
- Every decision is recorded with the evidence that produced it
- No agent is ever in a position to approve its own work

**Notes:** Say the line, then the third bullet slowly. That third bullet is the
thing that survives a compliance review. If a model could approve its own
output, the audit trail is decoration.

---

# What a delivery run looks like

| Stage | Who decides |
|---|---|
| Requirement refined into testable criteria | Code checks each is assertable |
| Design names what the change may touch | Code checks it against the codebase |
| **Agent writes the change** | Code reviews it before it is proposed |
| Tests run, scoped to what changed | Code decides pass or fail |
| Release recorded against the requirement | A person approves |

**Notes:** Walk down the right-hand column. The point is that "who decides" is
never the agent. Pause on row three — that is the row people assume is
ungoverned.

---

# It works. One cycle, end to end, last week

| Stage | What actually happened |
|---|---|
| Requirement | "Show how many claims are listed, updating with the filter" |
| Gates 1 and 2 | Approved by a person, each decision recorded |
| Implementation | A model wrote the change; review accepted it; committed to a branch |
| Verification | 11 scenarios, **scoped to 2 components** instead of the whole app. 12 browser tests, 0 failures |
| Release | Recorded to staging, linked to the files it contains |

- The change it wrote was **four lines**, idiomatic, and touched nothing else
- Afterwards the system could answer: no acceptance criterion is left untested

**Notes:** This is the slide to linger on. It is an observed run, not a design
intention — real model, real browser, real branch. If you only get one slide
across, make it this one. Have the four-line diff ready if someone asks.

---

# Two planes, one boundary

- **Control plane** — long-lived. Owns run state, gates, evidence, the audit trail
- **Execution plane** — ephemeral. Runs inside **the client's own CI**
- Nothing above the boundary executes untrusted code
- Nothing below it holds a credential that can change a decision

> We own the decisions and the evidence. We borrow the execution.

**Notes:** The quote is the architectural bet. The code, the credentials, the
runners and the compliance sign-off already live in the client's CI.
Re-homing that is a multi-quarter fight that adds no value — and trying to own
execution is how platforms like this die in an enterprise.

---

# Why that boundary sells

- Deploys behind the client's firewall with **no inbound network path**
- Their code never leaves their pipeline
- "Supports Jenkins" becomes one adapter, not a fork of the product
- Their existing test suites keep working — we drive them, we do not replace them

**Notes:** Each bullet kills an objection you will hear in a client security
review. The last one matters most: we connected to a real product repo that
already had its own end-to-end suite and CI, and needed to change nothing in
it.

---

# The differentiator: a context graph

- Requirement → criterion → design → change → test → run → defect → release
- Every edge records **which run created it and under which approval**
- It fills itself as a byproduct of the gates — no crawler, no reconciliation
- Holds identity and relationships only; the text stays in Jira, the code stays
  in the repo

**Notes:** This is the part competitors do not have and cannot bolt on later.
Everything else is orchestration. Do not go deeper than this slide unless
asked — the next slide has the payoff, which is what they will remember.

---

# What the graph makes possible

- **"Which requirements have never been verified by a passing test?"**
  A query. Not an archaeology exercise.
- **Test only what the change can affect.** Scope came from the dependency
  graph — one component the diff never touched was still tested, correctly
- **Contain the agent.** A change editing a component the design never named is
  refused before it is proposed
- **Trace an incident** back through component to requirement

**Notes:** Bullet one is the gate a regulated client actually asks about, and
it is not answerable from a run log. Bullet three is how we answer "what stops
it going rogue" — the honest answer is not "we asked it nicely", it is "a
build failure".

---

# Fits any client stack

- **10 integration points**, each swappable by configuration
- Requirements, source control, CI, model provider, test management, audit,
  deployment, code intelligence
- The **semantics are fixed**; only the integrations vary
- Every one has an offline default — the whole system demos with no keys and no
  network

**Notes:** Fixed semantics is the commercial point. If clients could redefine
the model, every engagement would fork the product and we would be a
consultancy with a codebase. This way an adapter is days, not a rebuild.

---

# The trust model

| Control | What it stops |
|---|---|
| Privilege split across two CI jobs | Generated code reaching a token that can write |
| Results pulled, never pushed | A forged result becoming run state |
| Deterministic change review | A change touching what nobody agreed to |
| Allowlist on generated tests | Obvious exfiltration paths |

- Secrets stay in the client's environment — never in our database

**Notes:** Expect the security question. The first two are structural: enforced
by the platform, not by anyone remembering. Be honest that row four is defence
in depth, not a sandbox — that honesty is what makes rows one and two credible.

---

# Where we actually are

**6 of 13 lifecycle phases running**

- **Real:** implementation, functional QA, all three human gates
- **Partial:** design, release readiness, deployment
- **Not built:** code review, security scanning, non-functional testing, data
  migration, post-deploy verification, feedback loop

**Notes:** Do not soften this. Being precise about what is scaffolding is what
makes the "real" column believable. Anyone who has sat through a vendor demo is
waiting to catch us overselling — beat them to it and the rest of the deck
gets trusted.

---

# Why one deep slice, not thirteen shallow ones

- Proving a single vertical — real requirement, real change, real browser, real
  evidence, real approver — establishes the architecture holds
- The remaining phases are **the same shape**: propose, decide, record, approve
- Filling them in is repetitive rather than risky

- **247 automated tests** hold the architecture in place, including tests that
  fail the build if the boundaries are crossed

**Notes:** The last bullet is worth saying out loud. Architectural rules that
live in a document get broken in the first busy week. Ours fail a build.

---

# What building it taught us

- **Implicit contracts produce confident, wrong answers.** An agent told a
  button exists — but not which screen it is on — guesses, and a wrong guess
  costs a full test run to discover
- **A pipeline that tests the wrong code proves nothing.** We found ours
  diffing the change and then testing the version before it
- **The gate caught a real defect** — a requirement the application genuinely
  did not satisfy, found from the requirement rather than by a person reading
  code

**Notes:** These are credibility, not confession. Every team that builds one of
these hits all three; most find out in front of a client. The third bullet is
the system doing its job and is worth telling as a story.

---

# What is needed next

1. **Identity** — approvals attributable to a named person. Nothing ships to a
   regulated client without it
2. **Evidence store** — durable artifacts; today they expire with the CI run
3. **One live run in a client's own CI** — the platform can already do this
   without their repository changing
4. **Parallel verification** + security scanning as the second verify phase
5. **Real confidence scoring**, then risk-tiered approval

**Notes:** Ordered by dependency, not appetite. Items 1 and 2 are unglamorous
and non-negotiable — do them before there are runs worth keeping, because both
rewrite storage. Item 5 is what makes this usable by a team merging daily
rather than a team doing a demo.

---

# The honest risks

- **Confidence is a placeholder today.** Risk-tiered approval cannot be switched
  on until it is real. Routing on a fabricated score is worse than no policy
- **Approve-everything does not scale.** A team merging daily will switch
  gating off wholesale unless tiering lands
- **Model behaviour changes under us.** We need an evaluation harness before we
  can tell an upgrade from a regression

**Notes:** Say these before anyone asks. The first one is the one a good CTO
will find. Having it on a slide with a plan attached is a much better position
than having it discovered.

---

# The ask

- **Endorse the architecture** — control plane decides, client's CI executes
- **Fund the next slice**: identity, evidence store, one live client CI run
- **Name a pilot client and a pilot repository** — the platform connects to an
  existing repo without changing it
- **Decide the IP boundary**: what is open, what is ours

**Notes:** Be specific about what a yes means this week. The pilot client is
the important one — everything after this point gets sharper with a real
codebase and a real compliance team asking real questions.

---

# In one sentence

## Agents do the work. The platform makes it defensible.

- One cycle proven end to end, on a real codebase
- Six of thirteen phases running, with a clear order for the rest
- Built to sit inside a client's existing toolchain, not replace it

**Notes:** Close here. Do not reopen the architecture. If there are questions,
take them against slide 5 — the run that actually happened.
