# Prompt: agentic SDLC — governed delivery reference architecture

Generated from the codebase. All 17 ports appear
exactly once, allocated to the side of the kernel they actually sit on.
Copy everything below the horizontal rule.

---

You are a principal enterprise architect producing the reference diagram for
a governed agentic software delivery platform, for executive leadership and
an architecture review board. Produce **one** diagram, landscape, roughly
2000×1150.

## Title block

Centred at the top:

> **Agentic SDLC — Governed AI Software Delivery**
> context before autonomy · deterministic authority · evidence before release

## Overall composition

A **left-to-right flow of seven columns**, with two full-width bands beneath
them. Every label horizontal. No circles, no polygons, no radial text.

```
enterprise      inbound      INBOUND    ┌──────────────┐   OUTBOUND    outbound     client
systems    →    adapters  →  PORTS   →  │  PLATFORM    │ →  PORTS   →  adapters  →  targets
of record       (BYO)                   │  (kernel)    │                (BYO)
                                        └──────────────┘
                     ── client execution trust boundary ──
                     ── zero trust and platform controls ──
```

The platform box is the visual centre of gravity: largest, most solid,
clearly bounded. Everything to its left and right is replaceable; nothing
inside it is.

---

## Column 1 — ENTERPRISE SYSTEMS OF RECORD

Small tiles, the client's existing estate. The platform does not replace
these:

- Requirements · Jira
- SCM and architecture repositories
- Source code · build graphs
- CMDB · catalogues · documents
- Enterprise identity
- Events · observability · ITSM

## Columns 2 + 3 — INBOUND ADAPTERS, AND THE PORTS THEY IMPLEMENT

Column 2 holds **BYO adapters** (label the column *"BYO source adapters —
platform default, client-built or partner"*). Column 3 holds the
**platform-owned port contracts** they implement. Draw an arrow from each
adapter to its port.

| Port (column 3) | Adapter (column 2) | Example implementations |
|---|---|---|
| `RequirementsSource` | Requirements adapter | Jira · Azure DevOps · Confluence · CSV |
| `EntityResolver` | Identity adapter | per-system identifier mapping |
| `CodeIntelligence` | Code intelligence adapter | GitHub AST indexer · local checkout · language server |
| `CodeDesignContext` | Grounding adapter | BM25 repo index · vector store · Confluence |

## Columns 5 + 6 — OUTBOUND PORTS, AND THE ADAPTERS BEHIND THEM

Column 5 is the **platform-owned outbound port contracts**; column 6 the
**BYO capability adapters**. Arrows run left to right, kernel → port →
adapter → target.

| Port (column 5) | Adapter (column 6) | Example implementations |
|---|---|---|
| `LLMProvider` | Model adapter | Claude · client-hosted model · mock |
| `DesignAgent` | Design agent adapter | in-process agent · client's design agent |
| `ImplementationAgent` | Implementation agent adapter | in-process agent · GitHub Copilot cloud agent |
| `QAAgent` | QA agent adapter | local pipeline · client's QA automation |
| `SourceControl` | SCM adapter | GitHub · GitLab · Bitbucket · local working copy |
| `WorkDispatch` | Work dispatch adapter | GitHub Actions · Jenkins · Azure Pipelines |
| `BuildDeploy` | Build + deploy adapter | no-op recorder · Jenkins · Argo CD · Octopus |
| `TestManagement` | Test management adapter | JSON file · Xray · TestRail · qTest |
| `AuditSink` | Evidence + audit adapter | SQLite · client SIEM · WORM store |

Mark `DesignAgent`, `ImplementationAgent` and `QAAgent` as a visually
grouped trio, with one caption: *"three agent seams, one contract — typed
request in, answer or receipt out"*. Draw a short arrow from that group to
`WorkDispatch` labelled *"delegates dispatch"* — when a client's agent runs
elsewhere, all three use the same waiting mechanism rather than one each.

## Column 7 — CLIENT / PROVIDER TARGETS

- Commercial or local models
- SCM repositories · branches · pull requests
- Test frameworks
- Data and environment services
- GitHub Actions · Jenkins · Kubernetes
- Artifact and release platforms
- Client SIEM · audit stores

---

## Column 4 — THE PLATFORM

One large bounded box, labelled **PLATFORM-PROVIDED — kernel · ports ·
contracts**. Inside it, four stacked lettered sections, then a band of
invariants.

**A. CONTROL AND GOVERNANCE**
Console + API · Workflow orchestrator · **Gate controller** · Adapter
registry · Reconciler
*caption:* deterministic decisions · checkpoints · human authority ·
resumability

Give the gate controller a distinct warm colour — it is where human
authority is enforced.

**B. DECISION INTELLIGENCE — one impact truth**
Semantic ChangeSet → **Impact Engine** → Test obligations → Release
readiness
*caption:* revision pair · typed propagation · explained paths · confidence
· blind spots

Make **Impact Engine** the largest element in the whole figure after the
platform box itself. Caption it: *"one canonical assessment — design,
implementation, QA and release consume the same one"*.

**C. CONTEXT AND EVIDENCE FABRIC**
Scope + identity · Ontology + semantics · Assertion ledger · Snapshot +
export · Retrieval · Evidence + audit
*caption:* deterministic identity · project-scoped · provenance on every
assertion · truth classes

Attach `ContextGraphStore` to this section as its **storage port** — drawn
on the boundary of the platform box with its own adapter chip outside
(*SQLite · PostgreSQL · Neo4j · hosted graph*). It is the one port that is
infrastructure rather than a party the platform talks to, and drawing it
here rather than in a side column is what says the storage engine is not the
architecture.

**D. EVALUATION AND GOVERNED PROMOTION**
Accuracy harness · Coherence checks · **Human review** · Controlled
promotion
*caption:* measured, not asserted · agents never rewrite their own controls

**CORE INVARIANTS** — a thin band across the bottom of the platform box:
project scope on every read and write · immutable decisions ·
deterministic authority · one impact assessment · evidence over assertion

---

## Band beneath — CLIENT EXECUTION TRUST BOUNDARY

A separate wide box below the platform, outlined in a **warning colour with
a dashed border**, labelled **CLIENT EXECUTION TRUST BOUNDARY — BYO
execution adapters**.

Inside it, left to right:

| Port | Adapter | Example implementations |
|---|---|---|
| `TestAuthor` | Test author adapter | in-process author · client's test agent |
| `TestDataProvider` | Test data adapter | JSON store · database lease · fixture service |
| `TestRunner` | Test runner adapter | Playwright · Cypress · pytest |

Plus: work dispatch runner · ephemeral workspace · evidence collector.

Caption beneath: *"source code, credentials and test data remain
client-side — the platform holds a revision pair and a result"*.

Draw one arrow from the platform's `QAAgent` port down into this box,
labelled *"authorised work order"*. This is the plane boundary: what happens
inside that box — script selection, test data, execution — belongs to the
client's provider.

---

## Bottom band — ZERO TRUST AND PLATFORM CONTROLS

A full-width band across the very bottom:

OIDC · workload identity · short-lived secrets · RBAC / ABAC · separation of
duties · egress allowlists · signed plugins / SBOM · telemetry · cost
budgets

---

## Legend

Top right, boxed:

- **Platform-provided boundary** — filled block
- **Stable framework kernel** — dark block
- **Platform port / contract** — outlined block
- **BYO adapter / provider** — outlined block with a "BYO" tag
- **External system** — plain block
- **Policy / human authority** — warm block

---

## Visual language

- Enterprise-architecture register: restrained, precise, printable. No neon,
  no gradients as decoration, no 3D, no drop shadows, no emoji, no clip art.
- A dark navy or slate for the kernel; a light tint for the platform
  boundary; white or grey for external systems; one warm accent used **only**
  for human authority — the gate controller, human review, and the trust
  boundary.
- One clean grotesque throughout. Port names in monospace or semibold so
  they read as contract names rather than prose.
- Every label horizontal and legible at 100%; nothing below about 11px at
  the drawn scale.

## Rules — what usually goes wrong

1. **Every name appears exactly once.** Count them before finishing.
   Duplicated ports and repeated implementation lists are the commonest
   failure.
2. **Invent nothing.** Use exactly the port names given. Do not coin a
   plausible one, and do not attach one port's implementations to another's
   label.
3. **Adapters are outside the platform box; ports are on its boundary.**
   That relationship is the entire claim of the diagram.
4. **Nothing in section A, B, C or D gets an adapter chip.** Those are not
   seams — they are the part that cannot be replaced.
5. **All port blocks are the same size.** No seam is more important than
   another.
6. The **flow direction is strictly left to right**; the only downward arrow
   is from `QAAgent` into the execution trust boundary.
7. No logo or footer.

## Output

Hand-authored **SVG**: self-contained, no external assets or fonts, a
`viewBox` set, explicit hex colours. Return it in one code block, then list
in plain text anything you shortened or omitted.

If you cannot produce SVG, produce a high-resolution image and say so first.
