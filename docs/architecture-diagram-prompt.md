# Prompt: agentic SDLC framework — polygonal ports-and-adapters diagram

Copy everything below the line into ChatGPT, Gemini or Claude.

---

You are a principal enterprise architect producing a reference diagram for an
executive and architecture-review audience. Produce **one** diagram. Accuracy
of structure matters more than decoration.

## What the system is

A governed agentic software delivery platform. AI agents propose and perform
delivery work; deterministic code decides what is admissible; people approve
at gate boundaries. It is built as ports and adapters (hexagonal
architecture), and the point of the diagram is that **every integration is a
replaceable seam, while the semantic core is fixed**.

## Overall geometry

Draw a **regular 16-sided polygon (hexadecagon)**, viewed flat-on, centred
on the canvas. Landscape, roughly 1600×1600 or 16:10 with the polygon
centred.

There are four zones, from outside in:

1. **Outside the polygon** — client-provided implementations, floating free.
2. **On each edge** — one port. The edge *is* the port.
3. **Inner ring, just inside the edges** — the SDLC cycle, running clockwise.
4. **Middle band** — the deterministic decision components.
5. **Centre** — the context graph and ontology.

Give each of the 16 edges a distinct segment. Label the port name **on the
edge itself**, oriented so it reads without rotating the page more than 90°.

## Zone 1 + 2 — the 16 ports, and what sits outside each

For each edge, write the port name on the edge, and place 2–4 example
client-provided implementations outside it as small chips. Use exactly these:

| # | Port (on the edge) | Outside the edge |
|---|---|---|
| 1 | RequirementsSource | Jira · Azure DevOps · Confluence · CSV |
| 2 | CodeIntelligence | GitHub AST indexer · local checkout · language server |
| 3 | CodeDesignContext | BM25 repo index · vector store · Confluence |
| 4 | ContextGraphStore | SQLite · PostgreSQL · Neo4j · hosted graph |
| 5 | EntityResolver | per-system id mapping |
| 6 | LLMProvider | Claude · client-hosted model · mock |
| 7 | DesignAgent | in-process agent · client's cloud agent |
| 8 | SourceControl | GitHub · GitLab · Bitbucket · local working copy |
| 9 | ImplementationAgent | in-process agent · GitHub Copilot cloud agent · client's coding agent |
| 10 | WorkDispatch | GitHub Actions · Jenkins · Azure Pipelines |
| 11 | TestManagement | JSON file · Xray · TestRail · qTest |
| 12 | AuditSink | SQLite · client SIEM · WORM store |
| 13 | BuildDeploy | no-op recorder · Jenkins · Argo CD · Octopus |
| 14 | TestAuthor | in-process author · client's test agent |
| 15 | TestDataProvider | JSON store · database lease · fixture service |
| 16 | TestRunner | Playwright · Cypress · pytest |

**Two agent seams, drawn identically.** `DesignAgent` (7) and
`ImplementationAgent` (9) are the two places a client substitutes their own
agent, and they are modelled the same way — a typed request in, either an
answer or a receipt out. Give those two edges the same visual treatment as
each other so the symmetry is visible.

**One arrow worth drawing.** `ImplementationAgent` and `TestAuthor`, when a
client's agent is dispatched rather than in-process, delegate the waiting to
`WorkDispatch` — reserve a row, park, reconcile. Draw a thin curved arrow
*inside* the polygon from each of those two edges to the `WorkDispatch`
edge, labelled "delegates dispatch". This is the only permitted edge-to-edge
line, and it makes the point that the platform has one waiting mechanism
rather than one per integration.

Mark ports 14, 15 and 16 (TestAuthor, TestDataProvider, TestRunner) as belonging to the **execution plane** — give their
three edges a subtly different edge treatment (for example a doubled line)
and add a small legend entry saying "execution plane — runs inside the
client's boundary". The other thirteen are control plane.

Two ports carry an **optional capability**, drawn as a small hollow tab on
the edge rather than a separate side:

- on CodeIntelligence: `RepositoryCatalogue` (optional)
- on BuildDeploy: `RollbackCapable` (optional)
- on ImplementationAgent: `AccessCheckable` (optional)

## Zone 3 — the SDLC cycle, on the inner ring

Just inside the polygon edges, draw a **clockwise cycle** of eight stages as
a ring of connected arrows. Starting at the top and moving clockwise:

1. Requirements intake
2. Requirements synthesis
3. **Gate 1 — human approval**
4. Design
5. **Gate 2 — human approval**
6. Implementation
7. QA execution
8. **Gate 3 — human approval** → Release

Draw the three gates visually distinct from the five phases — for example as
a narrow bar or a diamond across the ring — and label the gate band once:
"a person authorises every consequential transition".

Draw a return arrow from Release back to Requirements intake to close the
cycle.

## Zone 4 — the deterministic core, in the middle band

Between the SDLC ring and the centre, place these components as labelled
blocks. These are the parts that *decide*, and none of them is replaceable:

- **Impact Engine** — one canonical assessment: paths, confidence, test
  obligations, blind spots
- **Design review** — containment: a change may only touch what the design
  named
- **Change review** — what the agent actually did, checked against it
- **Release gate** — required regressions must have run and passed
- **Coverage & evidence** — a criterion is verified only by an observed run
- **Coherence checks** — configurations that build and cannot work
- **Snapshot & export** — the versioned projection the execution plane reads
- **Reconciler** — pulls results for work running elsewhere
- **Audit trail** — every decision, with its inputs

Make **Impact Engine** visually the largest of these and place it adjacent to
the centre — it is the component every phase consumes.

## Zone 5 — the centre

A distinct inner circle or smaller polygon, clearly the anchor of the whole
figure. Title it **Context Graph & Ontology**. Inside it, in smaller text:

- **Ontology** — 15 node types, 18 edge types, validated signatures
- **Identity** — deterministic: `uuid5(type | system | external_id)`
- **Scope** — every read and write names its project
- **Provenance** — every assertion carries how it was derived
- **Truth classes** — authoritative · derived · observed · inferred

Add one short line under the centre, in the figure: *"an LLM inference must
never be indistinguishable from a compiler-derived fact."*

## Visual language

- Professional, restrained, enterprise-architecture register. Not a
  marketing graphic, not neon, no gradients-as-decoration, no 3D, no
  drop-shadow clutter, no emoji, no clip-art icons.
- One accent hue for the centre and the Impact Engine. Neutral greys and a
  single cool tone for everything else. Semantic colour only for the three
  human gates.
- Typography: one clean grotesque. Port names on edges in small caps or
  letter-spaced uppercase; component labels sentence case.
- Every label must be legible at 100% zoom. If a label does not fit, shorten
  the label — never shrink it below roughly 11px at the drawn scale.
- Clear whitespace between the four zones so the concentric structure reads
  instantly.

## Rules — these are what usually go wrong

1. **Do not put adapters inside the polygon.** The boundary is the port; the
   implementations are outside it. That is the entire claim of the diagram.
2. **Do not draw arrows crossing the middle.** Nothing goes from an edge
   straight to the centre. Reads and writes go through the deterministic
   core.
3. **Do not make the SDLC cycle the outermost ring.** The ports are the
   outer boundary; the lifecycle runs inside them.
4. **Do not invent ports, phases or components.** Use exactly the labels
   above. If something will not fit, drop an *example implementation*, never
   a port.
5. **Do not add a "database" or "cloud" icon.** Storage is one port among
   sixteen and must not look like the foundation.
6. **Keep all sixteen edges equal.** No edge is more important than another
   — that equality is the pluggability argument.
7. Do not add a title block, logo, or footer.

## Output

Produce the diagram as **SVG**, hand-authored, self-contained, no external
assets or fonts, viewBox set, so it scales cleanly for print and slides. Use
`currentColor` or explicit hex — no CSS variables. Return the SVG in a single
code block, then list in plain text anything you had to shorten or omit.

If you cannot produce SVG, produce it as a high-resolution image and state
that limitation first.
