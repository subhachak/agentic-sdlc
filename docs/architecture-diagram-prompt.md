# Prompt: agentic SDLC framework — polygonal ports-and-adapters diagram

Generated from the codebase, not from memory: the port list below is
extracted from `class X(Protocol)` and every name is verified to exist.
Copy everything below the horizontal rule into ChatGPT, Gemini or Claude.

---

You are a principal enterprise architect producing a reference diagram for
an executive and architecture-review audience. Produce **one** diagram.
Structural accuracy matters more than decoration.

## What the system is

A governed agentic software delivery platform. AI agents propose and perform
delivery work; deterministic code decides what is admissible; people approve
at gate boundaries. It is built as ports and adapters, and the point of the
diagram is that **every integration is a replaceable seam while the semantic
core is fixed**.

## Overall geometry

Draw a **regular 17-sided polygon (heptadecagon)**, flat-on, centred.
Square canvas, roughly 1800×1800.

Five zones, outside in:

1. **Outside the polygon** — client-provided implementations, floating free
2. **On each edge** — one port; the edge *is* the port
3. **Inner ring** — the SDLC cycle, clockwise
4. **Middle band** — the deterministic decision components
5. **Centre** — the context graph and ontology

Label each port **on its edge**, oriented so no label needs the page rotated
more than 90°.

## Zones 1 + 2 — the 17 ports

Port name on the edge; 2–4 example implementations as small chips outside it.

**Control plane — 14 edges**

| # | Port | Outside the edge |
|---|---|---|
| 1 | RequirementsSource | Jira · Azure DevOps · Confluence · CSV |
| 2 | EntityResolver | per-system identifier mapping |
| 3 | CodeIntelligence | GitHub AST indexer · local checkout · language server |
| 4 | CodeDesignContext | BM25 repo index · vector store · Confluence |
| 5 | ContextGraphStore | SQLite · PostgreSQL · Neo4j · hosted graph |
| 6 | LLMProvider | Claude · client-hosted model · mock |
| 7 | DesignAgent | in-process agent · client's design agent |
| 8 | ImplementationAgent | in-process agent · GitHub Copilot cloud agent |
| 9 | QAAgent | local pipeline · client's QA automation |
| 10 | SourceControl | GitHub · GitLab · Bitbucket · local working copy |
| 11 | WorkDispatch | GitHub Actions · Jenkins · Azure Pipelines |
| 12 | TestManagement | JSON file · Xray · TestRail · qTest |
| 13 | BuildDeploy | no-op recorder · Jenkins · Argo CD · Octopus |
| 14 | AuditSink | SQLite · client SIEM · WORM store |

**Execution plane — 3 edges**

| # | Port | Outside the edge |
|---|---|---|
| 15 | TestAuthor | in-process author · client's test agent |
| 16 | TestDataProvider | JSON store · database lease · fixture service |
| 17 | TestRunner | Playwright · Cypress · pytest |

Give edges 15–17 a doubled line, and one legend entry: *"execution plane —
runs inside the client's boundary"*. The other fourteen are control plane.

### Three optional capabilities

Small hollow tabs on their edge, not sides of their own:

- CodeIntelligence → `RepositoryCatalogue`
- ImplementationAgent → `AccessCheckable`
- BuildDeploy → `RollbackCapable`

### Three structural facts to draw

**The three agent seams are identical.** `DesignAgent` (7),
`ImplementationAgent` (8) and `QAAgent` (9) are the three places a client
substitutes their own agent, and all three are modelled the same way: a
typed request in, either an answer or a receipt out. Place them adjacent and
give them matching treatment so the symmetry is visible.

**They delegate their waiting.** When a client's agent is dispatched rather
than in-process, all three hand the waiting to `WorkDispatch` (11). Draw a
thin curved arrow *inside* the polygon from each of 7, 8 and 9 to 11,
labelled once as "delegates dispatch". These are the only permitted
edge-to-edge lines. The point: one waiting mechanism, not one per
integration.

**QAAgent is the plane boundary.** When QA is dispatched, the thing at the
far end is the execution plane — which is where edges 15–17 live. Draw a
faint band or arc linking edge 9 to edges 15–17, labelled "the QA provider
owns script selection, test data and execution". Do not draw 15–17 as
subordinate boxes; they remain full edges of the polygon.

## Zone 3 — the SDLC cycle

Just inside the edges, a clockwise ring of eight stages. From the top:

1. Requirements intake
2. Requirements synthesis
3. **Gate 1 — human approval**
4. Design
5. **Gate 2 — human approval**
6. Implementation
7. QA execution
8. **Gate 3 — human approval** → Release

Draw the three gates distinctly from the five phases — a narrow bar or
diamond across the ring — and label the gate band once: *"a person
authorises every consequential transition"*. Close the cycle with a return
arrow from Release to Requirements intake.

## Zone 4 — the deterministic core

Between the SDLC ring and the centre. These decide, and none is replaceable:

- **Impact Engine** — one canonical assessment: paths, confidence, test
  obligations, blind spots
- **Design review** — containment: a change may touch only what the design named
- **Change review** — what the agent actually did, checked against it
- **Release gate** — required regressions must have run and passed
- **Coverage & evidence** — a criterion is verified only by an observed run
- **Coherence checks** — configurations that build and cannot work
- **Snapshot & export** — the versioned projection the execution plane reads
- **Reconciler** — pulls results for work running elsewhere
- **Audit trail** — every decision, with its inputs

Make **Impact Engine** the largest and place it adjacent to the centre — it
is what every phase consumes.

## Zone 5 — the centre

A distinct inner circle, clearly the anchor. Title: **Context Graph &
Ontology**. Inside, smaller:

- **Ontology** — 15 node types, 18 edge types, validated signatures
- **Identity** — deterministic: `uuid5(type | system | external_id)`
- **Scope** — every read and write names its project
- **Provenance** — every assertion carries how it was derived
- **Truth classes** — authoritative · derived · observed · inferred

One line beneath the centre, inside the figure: *"an LLM inference must never
be indistinguishable from a compiler-derived fact."*

## Visual language

- Professional, restrained, enterprise-architecture register. Not marketing.
  No neon, no gradients as decoration, no 3D, no drop-shadow clutter, no
  emoji, no clip-art icons.
- One accent hue for the centre and the Impact Engine. Neutral greys and a
  single cool tone elsewhere. Semantic colour only for the three human gates.
- One clean grotesque throughout. Port names letter-spaced uppercase;
  component labels sentence case.
- Every label legible at 100%. If a label will not fit, shorten the label —
  never take it below ~11px at the drawn scale.
- Clear whitespace between zones so the concentric structure reads instantly.

## Rules — these are what usually go wrong

1. **Adapters never go inside the polygon.** The boundary is the port; the
   implementations sit outside it. That is the entire claim of the diagram.
2. **Nothing crosses the middle.** No arrow runs from an edge to the centre.
   Reads and writes go through the deterministic core.
3. **The SDLC cycle is not the outer ring.** Ports are the outer boundary;
   the lifecycle runs inside them.
4. **Invent nothing.** Use exactly the labels above. If something will not
   fit, drop an *example implementation* — never a port. A diagram with 15
   edges claiming 17 seams is worse than no diagram.
5. **No database or cloud icon.** Storage is one port among seventeen and
   must not look like the foundation.
6. **All seventeen edges are equal.** That equality is the pluggability
   argument.
7. Only the four permitted internal lines exist: three "delegates dispatch"
   arrows, and the QA-to-execution-plane band.
8. No title block, logo or footer.

## Output

Hand-authored **SVG**: self-contained, no external assets or fonts,
`viewBox` set, explicit hex colours (no CSS variables), so it scales for
print and slides. Return it in one code block, then list in plain text
anything you shortened or omitted.

If you cannot produce SVG, produce a high-resolution image and say so first.
