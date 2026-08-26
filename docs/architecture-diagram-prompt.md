# Prompt: agentic SDLC framework — layered reference architecture

Generated from the codebase; all 17 ports are present
and each appears once. Copy everything below the horizontal rule.

---

You are a principal enterprise architect producing the reference diagram for
a governed agentic software delivery platform. The audience is executive
leadership and an architecture review board. Produce **one** diagram.
Structural accuracy matters more than decoration.

## The single idea the diagram must carry

Agents propose and perform delivery work. **Deterministic code decides what
is admissible.** People authorise every consequential transition. Everything
the platform touches on the outside is a replaceable seam; the part that
decides is fixed and is not replaceable.

Read the figure top to bottom as four stacked bands:

> what happens → what decides → what it stands on → what it plugs into

## Layout

Landscape, roughly 1920×1200. Four full-width horizontal bands, stacked,
with clear separation. No circles, no polygons, no radial text — every label
horizontal.

---

### Band 1 (top) — THE DELIVERY LIFECYCLE

A single left-to-right flow of nine stages with arrows between them:

Requirements intake → Requirements synthesis → **Gate 1** → Design → **Gate 2** → Implementation → QA execution → **Gate 3** → Release

The three **Gate** stages are human approvals: draw them visually distinct
from the six phases — a different shape (narrow vertical bar or diamond) and
a separate colour. Label the band once, small: *"a person authorises every
consequential transition"*.

Add a thin return arrow from Release back to Requirements intake beneath the
row, so the lifecycle reads as a cycle rather than a one-way pipe.

---

### Band 2 — THE DETERMINISTIC CORE

A wide slab directly beneath the lifecycle, visually the most solid element
on the page. Label it **"the deterministic core — not replaceable"**.

Inside it, nine components as a row or two rows of tiles:

- **Impact Engine** — one assessment: paths, confidence, test obligations, blind spots
- **Design review** — a change may touch only what the design named
- **Change review** — what the agent actually did, checked against it
- **Release gate** — required regressions must have run and passed
- **Coverage & evidence** — a criterion is verified only by an observed run
- **Coherence checks** — configurations that build and cannot work
- **Snapshot & export** — the versioned projection the execution plane reads
- **Reconciler** — pulls results for work running elsewhere
- **Audit trail** — every decision, with its inputs

Make **Impact Engine** noticeably larger than the rest and place it first or
centre. It is the one thing every phase consumes. Give it a short caption:
*"one canonical assessment — every phase consumes the same one"*.

Draw short arrows from Band 1 down into this slab, showing that the
lifecycle asks the core rather than deciding for itself.

---

### Band 3 — THE CONTEXT GRAPH AND ONTOLOGY

A distinct full-width band beneath the core, in the accent colour — this is
the foundation everything above rests on. Title it **Context Graph &
Ontology**.

Five compartments across it:

- **Ontology** — 15 node types · 18 edge types · validated signatures
- **Identity** — uuid5(type | system | external_id)
- **Scope** — every read and write names its project
- **Provenance** — every assertion carries how it was derived
- **Truth classes** — authoritative · derived · observed · inferred

Beneath the band, one italic line: *"an LLM inference must never be
indistinguishable from a compiler-derived fact."*

The core in Band 2 should sit visually *on* this band, so the reader sees
that the decisions rest on it.

---

### Band 4 (bottom) — THE PORT BOUNDARY, AND WHAT PLUGS INTO IT

This is the most important band to get right.

Draw **one continuous horizontal membrane** — a single long bar spanning the
full width, clearly a boundary rather than a container. Label it once, at
the left edge: **"ports — every integration is a replaceable seam"**.

Divide the membrane into 17 labelled cells, grouped and
separated as below. Put the port name inside its cell.

Below the membrane, outside the platform, list each port's example
implementations as small grey text. These are the client's systems — they
sit **outside** the boundary and are swapped per engagement.

**Intake**

- `RequirementsSource` — Jira · Azure DevOps · Confluence · CSV
- `EntityResolver` — per-system identifier mapping
**Codebase**

- `CodeIntelligence` — GitHub AST indexer · local checkout · language server
- `CodeDesignContext` — BM25 repo index · vector store · Confluence
- `ContextGraphStore` — SQLite · PostgreSQL · Neo4j · hosted graph
**Agents**

- `LLMProvider` — Claude · client-hosted model · mock
- `DesignAgent` — in-process agent · client's design agent
- `ImplementationAgent` — in-process agent · GitHub Copilot cloud agent
- `QAAgent` — local pipeline · client's QA automation
**Test execution**

- `TestAuthor` — in-process author · client's test agent
- `TestDataProvider` — JSON store · database lease · fixture service
- `TestRunner` — Playwright · Cypress · pytest
**Delivery**

- `WorkDispatch` — GitHub Actions · Jenkins · Azure Pipelines
- `SourceControl` — GitHub · GitLab · Bitbucket · local working copy
- `BuildDeploy` — no-op recorder · Jenkins · Argo CD · Octopus
**Evidence**

- `TestManagement` — JSON file · Xray · TestRail · qTest
- `AuditSink` — SQLite · client SIEM · WORM store

Mark the three **Test execution** cells as belonging to the *execution
plane*, with a different cell treatment and one legend entry: *"execution
plane — runs inside the client's boundary; the platform never sees the
source"*. The other 14 are control plane.

Three ports carry an **optional capability** — draw a small dashed tag on
the cell, not a new cell:

- `CodeIntelligence` → RepositoryCatalogue
- `ImplementationAgent` → AccessCheckable
- `BuildDeploy` → RollbackCapable

**One relationship to draw inside the membrane.** `DesignAgent`,
`ImplementationAgent` and `QAAgent` are modelled identically — a typed
request in, either an answer or a receipt out. When a client's agent runs
elsewhere, all three delegate the waiting to `WorkDispatch`. Draw three thin
arrows from those cells to the `WorkDispatch` cell, labelled once
*"delegates dispatch"*. The point: one waiting mechanism, not one per
integration.

---

## Visual language

- Enterprise-architecture register: restrained, precise, printable. No neon,
  no gradients as decoration, no 3D, no drop shadows, no emoji, no icons, no
  clip art.
- One accent hue, used for the Context Graph band and the Impact Engine
  only. Neutral greys elsewhere. One separate warm tone for the three human
  gates.
- A single clean grotesque. Port names in the membrane semibold; client
  implementations below it small and grey; band titles small caps.
- Every label horizontal and legible at 100%. If a label does not fit,
  shorten the label — never take it below ~12px at the drawn scale.

## Rules — what usually goes wrong

1. **Every name appears exactly once.** Count them before you finish.
   Duplicated ports and repeated implementation lists are the commonest
   failure.
2. **Invent nothing.** Use exactly the names given. Do not coin a plausible
   port; do not attach one port's implementations to another's label.
3. **Client implementations go below the membrane, never above it.** The
   membrane is the boundary; what fills it is outside. That is the whole
   claim.
4. **The core and the graph are not seams.** Nothing in Bands 2 or 3 gets a
   client implementation chip.
5. **Bands must be visually distinct** and read in order top to bottom.
6. **All 17 port cells are the same size.** That
   equality is the pluggability argument — no cell is more important.
7. No title block, logo, or footer.

## Output

Hand-authored **SVG**: self-contained, no external assets or fonts, a
`viewBox` set, explicit hex colours. Return it in one code block, then list
in plain text anything you shortened or omitted.

If you cannot produce SVG, produce a high-resolution image and say so first.
