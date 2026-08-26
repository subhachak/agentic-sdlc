# Prompt: agentic SDLC framework — grouped octagon

Generated from the codebase. The eight families below are verified to
partition all 17 ports, so nothing is silently dropped.
Copy everything below the horizontal rule.

---

You are a principal enterprise architect producing a reference diagram for
an executive and architecture-review audience. Produce **one** diagram.
Structural accuracy matters more than decoration.

## What the system is

A governed agentic software delivery platform. AI agents propose and perform
delivery work; deterministic code decides what is admissible; people approve
at gate boundaries. It is built as ports and adapters, and the diagram's job
is to show that **every integration is a replaceable seam while the semantic
core is fixed**.

## Geometry

A **regular octagon**, flat-on, centred on a square canvas (about
1800×1800). One edge is centred at the top — rotate the polygon by half a
step so a *vertex* is not at twelve o'clock, because the labels live on
edges.

Five zones, outside in:

1. Outside the polygon — the ports each family contains
2. On each edge — the family name
3. Inner ring — the SDLC cycle, clockwise
4. Middle band — the deterministic decision components
5. Centre — the context graph and ontology

Leave a clear gap between the polygon edge and the SDLC ring. An octagon
pulls its edge midpoints about 8% closer to the centre than a many-sided
polygon does, so labels crowd there if the rings are placed generously.

## Zones 1 + 2 — the eight seam families

Family name **on the edge**, rotated to lie along it and never upside down.
The ports it contains as small text just outside, horizontal, anchored away
from the centre.

| # | On the edge | Outside it |
|---|---|---|
| 1 | Intake | RequirementsSource · EntityResolver |
| 2 | Code context | CodeIntelligence · CodeDesignContext · ContextGraphStore |
| 3 | Models | LLMProvider |
| 4 | Agents | DesignAgent · ImplementationAgent · QAAgent |
| 5 | Test execution | TestAuthor · TestDataProvider · TestRunner |
| 6 | Remote work | WorkDispatch |
| 7 | Delivery | SourceControl · BuildDeploy · TestManagement |
| 8 | Evidence | AuditSink |

Give the **Test execution** edge a doubled line and one legend entry:
*"execution plane — runs inside the client's boundary"*. The other seven are
control plane.

Three optional capabilities, drawn as small dashed tabs on the *inside* of
their family's edge rather than as sides of their own:

- Code context → `RepositoryCatalogue`
- Agents → `AccessCheckable`
- Delivery → `RollbackCapable`

**One structural note to draw.** The three ports in **Agents** —
DesignAgent, ImplementationAgent, QAAgent — are modelled identically: a
typed request in, either an answer or a receipt out. When a client's agent
is dispatched rather than in-process, all three hand the waiting to
WorkDispatch in **Remote work**. Draw one thin curved arrow inside the
polygon from the Agents edge to the Remote work edge, labelled "delegates
dispatch". It is the only permitted edge-to-edge line, and it says the
platform has one waiting mechanism rather than one per integration.

## Zone 3 — the SDLC cycle

Nine stages clockwise from the top, on a tinted annulus:

1. Requirements intake
2. Requirements synthesis
3. **Gate 1 — human approval**
4. Design
5. **Gate 2 — human approval**
6. Implementation
7. QA execution
8. **Gate 3 — human approval**
9. Release

Draw the three gates as small filled squares straddling the ring, in a
distinct colour from the five phases, and label the band once: *"a person
authorises every consequential transition"*. Close the cycle with a return
arrow from Release to Requirements intake.

## Zone 4 — the deterministic core

Between the SDLC ring and the centre. These decide, and none is replaceable:

- **Impact Engine** — one assessment: paths, confidence, test obligations, blind spots  ← largest, nearest the centre
- **Design review** — a change may touch only what the design named
- **Change review** — what the agent actually did, checked against it
- **Release gate** — required regressions must have run and passed
- **Coverage & evidence** — a criterion is verified only by an observed run
- **Coherence checks** — configurations that build and cannot work
- **Snapshot & export** — the versioned projection the execution plane reads
- **Reconciler** — pulls results for work running elsewhere
- **Audit trail** — every decision, with its inputs

## Zone 5 — the centre

A distinct inner circle, clearly the anchor. Title **Context Graph &
Ontology**, and inside it, smaller:

- **Ontology** — 15 node types · 18 edge types · validated signatures
- **Identity** — uuid5(type | system | external_id)
- **Scope** — every read and write names its project
- **Provenance** — every assertion carries how it was derived
- **Truth classes** — authoritative · derived · observed · inferred

One italic line at the bottom of the circle: *"an LLM inference must never be
indistinguishable from a compiler-derived fact."*

Centre this block vertically inside the circle. Hanging it from the top
leaves the bottom third empty and reads as a mistake.

## Visual language

- Professional, restrained, enterprise-architecture register. No neon, no
  gradients as decoration, no 3D, no drop shadows, no emoji, no icons.
- One accent hue for the centre and the Impact Engine. Neutral greys and a
  single cool tone elsewhere. A separate warm tone for the three gates only.
- One clean grotesque. Family names on edges in semibold; component labels
  sentence case; the ports outside the edges small and grey.
- Every label legible at 100%. If a label will not fit, shorten it — never
  below about 11px at the drawn scale.

## Rules — these are what actually go wrong

1. **It must be a polygon with visible straight edges.** Concentric circles
   are the common failure: once the edges are gone nothing sits *on* one,
   and the claim "the boundary is the port" disappears with them.
2. **Each label appears exactly once.** Count them before you finish. A
   duplicated family or a repeated implementation list is the second common
   failure.
3. **Invent nothing.** Use exactly the names above. Do not coin a plausible
   port; do not attach one family's ports to another's label.
4. **Adapters never go inside the polygon.** The boundary is the seam; what
   fills it sits outside.
5. **Nothing crosses the middle.** No arrow runs from an edge to the centre.
6. **The SDLC cycle is not the outer ring.** The seams are the outer
   boundary; the lifecycle runs inside them.
7. **All eight edges are equal.** That equality is the pluggability
   argument.
8. No title block, logo or footer.

## Output

Hand-authored **SVG**: self-contained, no external assets or fonts,
`viewBox` set, explicit hex colours. Return it in one code block, then list
in plain text anything you shortened or omitted.

If you cannot produce SVG, produce a high-resolution image and say so first.
