"""Node implementations for this phase: trivial pass-through/echo business
logic (real agent reasoning is a later phase) plus thin gate nodes.

Only ever sees `ports/` Protocol types and `core/` — never imports a
concrete `adapters/` module. Adapter instances are constructed once in
main.py's lifespan (via adapters/registry.py) and passed in here already
built.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.agents.state import GateDecision
from app.core.audit import AuditLogger, NodeFn, audited
from app.agents.design import SYSTEM as DESIGN_SYSTEM
from app.agents.design import DesignProposal
from app.agents.design import build_prompt as build_design_prompt
from app.agents.implementation import SYSTEM as IMPLEMENTATION_SYSTEM
from app.agents.implementation import Implementation, build_prompt
from app.core.change_review import review as review_change
from app.core.design_review import MAX_FILES as MAX_DESIGN_FILES
from app.core.seeding import refresh as refresh_index
from app.core.design_review import review as review_design
from app.core.context_graph import Assertion, ContextGraphStore, NodeSpec
from app.core.dispatches import DispatchStore
from app.core.gate_controller import GateController
from app.core.reliability import with_retry_fallback
from app.ports.build_deploy import BuildDeploy
from app.ports.code_design_context import CodeDesignContext
from app.ports.code_intelligence import CodeIntelligence
from app.ports.llm_provider import LLMProvider
from app.ports.requirements_source import RequirementsInput, RequirementsSource
from app.ports.source_control import ChangeRef, FileEdit, SourceControl
from app.ports.test_management import TestCaseRecord, TestManagement
from app.ports.work_dispatch import DispatchResult, WorkDispatch


def _assertions_from(payload: dict[str, Any]) -> list[Assertion]:
    """Translate the execution plane's assertion list into core types.

    The wire format is deliberately plain dicts: the execution plane is a
    separate package that cannot import these classes, and a shared schema
    across a process boundary is a coupling that would have to be versioned.
    """
    out: list[Assertion] = []
    for raw in payload.get("assertions", []) or []:
        try:
            out.append(
                Assertion(
                    edge=raw["edge"],
                    src=NodeSpec(**raw["src"]),
                    dst=NodeSpec(**raw["dst"]),
                    attributes=raw.get("attributes", {}),
                )
            )
        except (KeyError, TypeError):
            continue  # a malformed assertion is dropped, never crashes the phase
    return out


# How many times the design agent may revise after a rejection. Overridable
# per build, and previously not: the parameter existed and the loop read the
# module constant, so passing a different value changed nothing.
DEFAULT_DESIGN_ATTEMPTS = 3

# How many code excerpts the design agent is shown. Three was a placeholder
# from when grounding was two fixture documents; retrieval now returns
# symbol-level chunks, where the relevant one is often not in the top three.
DESIGN_SNIPPETS = 10


def build_nodes(
    *,
    requirements_source: RequirementsSource,
    code_design_context: CodeDesignContext,
    test_management: TestManagement,
    build_deploy: BuildDeploy,
    work_dispatch: WorkDispatch,
    source_control: SourceControl,
    code_intelligence: CodeIntelligence | None = None,
    dispatch_store: DispatchStore,
    context_graph: ContextGraphStore,
    llm_provider: LLMProvider,  # unused by stub logic this phase; wired for later phases
    audit_logger: AuditLogger,
    gate_controller: GateController,
    max_retries: int,
    design_attempts: int = DEFAULT_DESIGN_ATTEMPTS,
    dispatch_timeout_seconds: int = 1800,
    dispatch_provider: str = "local",
    target_repo: str = "",
    target_ref: str = "main",
    target_environment: str = "staging",
) -> dict[str, NodeFn]:
    def business(name: str, fallback: dict[str, Any]):
        def decorator(fn: NodeFn) -> NodeFn:
            wrapped = with_retry_fallback(name, lambda _state: dict(fallback), max_retries)(fn)
            return audited(name, audit_logger)(wrapped)

        return decorator

    @business("requirements_intake", fallback={"status": "requirements_intake_failed"})
    async def requirements_intake(state: dict[str, Any]) -> dict[str, Any]:
        raw = RequirementsInput(**state["raw_input"])
        doc = await requirements_source.fetch(raw)
        return {"raw_requirements": doc.model_dump(), "status": "synthesizing"}

    @business("requirements_synthesis", fallback={"status": "synthesis_failed"})
    async def requirements_synthesis(state: dict[str, Any]) -> dict[str, Any]:
        raw = state["raw_requirements"]
        synthesis = {
            "summary": raw["text"][:280],
            "item_count": raw["item_count"],
            "source_type": raw["source_type"],
            "note": "stub — echoes raw input into a placeholder structured shape",
        }
        return {"requirements_synthesis": synthesis, "status": "checking_ambiguity"}

    @business("ambiguity_check", fallback={"status": "ambiguity_check_failed"})
    async def ambiguity_check(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "ambiguity_check": {"passed": True, "reason": "stub — deterministic rule always passes"},
            "status": "awaiting_gate_1",
        }

    async def gate_1(state: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "type": "requirements_approval",
            "requirements_synthesis": state.get("requirements_synthesis"),
            "ambiguity_check": state.get("ambiguity_check"),
        }
        decision = await gate_controller.request_gate(state, "gate_1", payload)
        gate_decision = GateDecision(
            gate_name="gate_1",
            approved=bool(decision.get("approved")),
            feedback=decision.get("feedback"),
            decided_at=datetime.now(timezone.utc),
        )
        return {
            "gate1_decision": gate_decision,
            "status": "designing" if gate_decision.approved else "rejected_at_gate_1",
        }

    @business("design_proposal", fallback={"status": "design_proposal_failed"})
    async def design_proposal(state: dict[str, Any]) -> dict[str, Any]:
        """Decide what the change will touch, and prove it exists.

        This phase is load-bearing: the implementation phase may only edit what
        it names, so a design that guesses makes containment meaningless. The
        agent chooses from a catalogue of modules that actually exist, and
        every name it returns is checked against the graph before a human is
        asked to approve anything.

        The impact set is not proposed. It is derived from dependency edges,
        because an architect can be wrong about consequences.
        """
        requirement = (state.get("raw_input") or {}).get("text", "")
        query = (state.get("requirements_synthesis") or {}).get("summary", "") or requirement
        snippets = [
            s.model_dump()
            for s in await code_design_context.retrieve_context(query, DESIGN_SNIPPETS)
        ]

        catalogue = await context_graph.module_catalogue()
        known_paths = await context_graph.module_paths()
        file_dependents = await context_graph.file_dependents()
        criteria = await context_graph.criteria()
        known_criteria = {c["id"] for c in criteria if c.get("id")}
        # How complete the graph behind those edges is. A design cannot be
        # meaningfully contained by a graph that dropped a fifth of the
        # codebase's imports, so the review is told and refuses.
        graph_quality = await context_graph.index_provenance()

        base_prompt = build_design_prompt(
            requirement=requirement,
            criteria=criteria,
            catalogue=catalogue,
            snippets=snippets,
            max_files=MAX_DESIGN_FILES,
        )

        reasons: list[str] = []
        proposal = None
        for attempt in range(1, design_attempts + 1):
            prompt = base_prompt if not reasons else (
                base_prompt
                + "\n\nYour previous design was rejected:\n"
                + "\n".join(f"- {r}" for r in reasons)
                + "\n\nName only modules and files from the catalogue above."
            )
            proposal = await llm_provider.complete_json(DESIGN_SYSTEM, prompt, DesignProposal)

            if proposal.blocked:
                return {
                    "design_proposal": {"blocked": proposal.blocked, "summary": proposal.summary},
                    "status": "design_blocked",
                }

            verdict = review_design(
                proposal.model_dump(),
                known_modules=known_paths,
                file_dependents=file_dependents,
                known_criteria=known_criteria,
                graph_quality=graph_quality,
            )
            if verdict.allowed:
                return {
                    "design_proposal": {
                        **proposal.model_dump(),
                        "impact": verdict.impact,
                        "context_snippets": snippets,
                        "attempts": attempt,
                        "notes": verdict.reasons,
                    },
                    "status": "awaiting_gate_2",
                }
            reasons = verdict.reasons

        return {
            "design_proposal": {
                **(proposal.model_dump() if proposal else {}),
                "rejected": reasons,
                "attempts": design_attempts,
            },
            "status": "design_rejected",
        }

    async def gate_2(state: dict[str, Any]) -> dict[str, Any]:
        design = state.get("design_proposal") or {}
        payload = {
            "type": "design_approval",
            "summary": design.get("summary"),
            "rationale": design.get("rationale"),
            "modules": design.get("modules"),
            "files": design.get("files"),
            "impact": design.get("impact"),
            "criteria_addressed": design.get("criteria_addressed"),
            "out_of_scope": design.get("out_of_scope"),
            "risks": design.get("risks"),
        }
        decision = await gate_controller.request_gate(state, "gate_2", payload)
        gate_decision = GateDecision(
            gate_name="gate_2",
            approved=bool(decision.get("approved")),
            feedback=decision.get("feedback"),
            decided_at=datetime.now(timezone.utc),
        )
        return {
            "gate2_decision": gate_decision,
            "status": "generating_tests" if gate_decision.approved else "rejected_at_gate_2",
        }

    @business("test_case_generation", fallback={"status": "test_case_generation_failed"})
    async def test_case_generation(state: dict[str, Any]) -> dict[str, Any]:
        tc = TestCaseRecord(
            id=str(uuid4()),
            run_id=state["run_id"],
            story_ref="stub-story-1",
            gherkin_text="Given a submitted requirement\nWhen the pipeline runs\nThen a test case is drafted (stub)",
        )
        await test_management.create_test_case(state["run_id"], tc)
        return {"test_cases": [tc.model_dump()], "status": "awaiting_qa_execution"}

    @business("implementation", fallback={"status": "implementation_failed"})
    async def implementation(state: dict[str, Any]) -> dict[str, Any]:
        """Write the change, review it deterministically, propose it.

        The review is the load-bearing part. An agent that edits a module
        the design never mentioned is not implementing the design, and the
        context graph is what makes that checkable rather than a matter of
        opinion.
        """
        design = state.get("design_proposal") or {}
        allowed = [c for c in design.get("modules", []) if c]
        candidate_paths = [p for p in design.get("files", []) if p]

        files = (
            await source_control.read_files(target_repo, target_ref, candidate_paths)
            if candidate_paths
            else {}
        )

        proposal = await llm_provider.complete_json(
            IMPLEMENTATION_SYSTEM,
            build_prompt(
                requirement=state.get("raw_input", {}).get("text", ""),
                design=design,
                criteria=await context_graph.criteria(),
                files=files,
                allowed_modules=allowed,
            ),
            Implementation,
        )

        if proposal.blocked:
            return {
                "implementation": {"blocked": proposal.blocked, "summary": proposal.summary},
                "status": "implementation_blocked",
            }

        edits = [e.model_dump() for e in proposal.edits]
        known = await context_graph.module_paths()
        verdict = review_change(
            edits, allowed_modules=allowed, known_modules=known
        )

        if not verdict.allowed:
            return {
                "implementation": {
                    "summary": proposal.summary,
                    "rejected": verdict.reasons,
                    "files": [e["path"] for e in edits],
                },
                "status": "implementation_rejected",
            }

        change: ChangeRef = await source_control.open_change(
            target_repo,
            target_ref,
            f"agentic/{state['run_id'][:8]}",
            f"{proposal.summary[:70]}",
            f"{proposal.summary}\n\nProposed by the agentic SDLC pipeline for run "
            f"{state['run_id']}.",
            [FileEdit(path=e["path"], content=e["content"]) for e in edits],
        )

        return {
            "implementation": {
                "summary": proposal.summary,
                "files": change.files,
                "modules": verdict.modules,
                "branch": change.branch,
                "url": change.url,
                "commit": change.commit,
                "base_commit": change.base_commit,
            },
            # The revision pair the QA phase tests between. These used to be
            # read out of state by the dispatch node and written by nothing,
            # so a remote run received two empty strings and its workflow fell
            # back to the default branch — testing the code that was already
            # there rather than the change just made.
            "base_sha": change.base_commit or "",
            "head_sha": change.commit or "",
            "changed_paths": change.files,
            "status": "awaiting_qa_execution",
        }

    async def qa_execution(state: dict[str, Any]) -> dict[str, Any]:
        """Hand the QA phase to whatever actually runs it, then park.

        Deliberately not wrapped in `with_retry_fallback`, for the same
        reason gate nodes are not: a parked node is not a transient failure,
        and falling back would mean reporting a QA verdict that no test
        produced. Retries belong inside the adapter's HTTP calls, where a
        flaky response genuinely is transient.
        """
        run_id = state["run_id"]
        head_sha = state.get("head_sha") or ""

        # A dispatch with no revision has nothing to test. Refusing is the
        # only honest outcome: the executor would otherwise check out its
        # default branch and report a verdict on code this run never touched,
        # which reads exactly like a passing QA result.
        if not head_sha:
            return {
                "qa_result": {
                    "gate_passed": False,
                    "reasons": [
                        "the implementation phase produced no commit to test, so the "
                        "QA phase was not dispatched"
                    ],
                },
                "status": "qa_failed",
            }

        # None means a row already exists, i.e. this is the resume pass and
        # the job is already running. Triggering here would start a second.
        claimed = await dispatch_store.claim(
            run_id, "qa", dispatch_provider, dispatch_timeout_seconds
        )
        if claimed is not None:
            try:
                handle = await work_dispatch.trigger(
                    run_id,
                    "qa",
                    claimed.correlation_id,
                    {
                        "base_sha": state.get("base_sha", ""),
                        "head_sha": head_sha,
                        # What the implementation phase actually touched. The QA
                        # pipeline widens this to the blast radius itself.
                        "changed_paths": state.get("changed_paths", []),
                        "branch": (state.get("implementation") or {}).get("branch", ""),
                    },
                )
                await dispatch_store.attach_external(
                    claimed.id, handle.external_id, handle.external_url
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a failed dispatch
                await dispatch_store.resolve(
                    claimed.id,
                    DispatchResult(state="failed", detail=f"could not trigger: {exc}"),
                )

        result = await gate_controller.request_external(
            state, "qa_execution", {"type": "qa_execution", "phase": "qa"}
        )

        outcome = result.get("state", "failed")

        # The QA phase already knows which criterion each scenario covers and
        # which script ran it. Those are the graph's edges, so they are written
        # here rather than by any separate ingestion job — and they carry the
        # run that asserted them.
        payload = result.get("payload") or {}
        edges_written = await context_graph.ingest(
            run_id, "qa", _assertions_from(payload)
        )

        return {
            "qa_result": result,
            "graph_edges_written": edges_written,
            "status": "awaiting_gate_3" if outcome == "succeeded" else f"qa_{outcome}",
        }

    async def gate_3(state: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "type": "test_case_approval",
            "test_cases": state.get("test_cases", []),
            "qa_result": state.get("qa_result"),
        }
        decision = await gate_controller.request_gate(state, "gate_3", payload)
        gate_decision = GateDecision(
            gate_name="gate_3",
            approved=bool(decision.get("approved")),
            feedback=decision.get("feedback"),
            decided_at=datetime.now(timezone.utc),
        )
        return {
            "gate3_decision": gate_decision,
            "status": "building" if gate_decision.approved else "rejected_at_gate_3",
        }

    @business("release", fallback={"status": "release_failed"})
    async def release(state: dict[str, Any]) -> dict[str, Any]:
        """Ship, and record what shipped.

        The deployment itself is still whatever the BuildDeploy adapter does.
        What is new is the trail: a release node with edges to the files it
        contains and the environment it reached, which is what turns "when did
        this criterion last ship" into a query.
        """
        implementation = state.get("implementation") or {}
        result = await build_deploy.trigger_build(
            state["run_id"],
            {
                "branch": implementation.get("branch", ""),
                "files": implementation.get("files", []),
            },
        )

        release_id = f"{state['run_id'][:8]}"
        release_node = NodeSpec("RELEASE", "pipeline", release_id, {
            "build_id": result.build_id, "branch": implementation.get("branch", "")
        })
        assertions = [
            Assertion(
                "CONTAINS",
                release_node,
                NodeSpec("SOURCE_ARTIFACT", "code", path, {}),
            )
            for path in implementation.get("files", [])
        ]
        assertions.append(
            Assertion(
                "DEPLOYED_TO",
                release_node,
                NodeSpec("ENVIRONMENT", "pipeline", target_environment, {}),
            )
        )
        await context_graph.ingest(state["run_id"], "release", assertions)

        # The run just changed the codebase, so the graph now describes the
        # commit before it. Refreshing here is what keeps "what depends on
        # what" true between runs rather than only after someone remembers to
        # re-index — and it reports the delta, so a release says what it moved
        # in the graph as well as what it shipped.
        graph_update: dict[str, Any] = {"skipped": "no indexer configured"}
        if code_intelligence is not None and target_repo:
            try:
                summary = await refresh_index(
                    context_graph,
                    code_intelligence,
                    repo=target_repo,
                    ref=implementation.get("branch") or target_ref,
                    run_id=state["run_id"],
                )
                graph_update = {
                    "commit_sha": summary.get("commit_sha"),
                    **summary.get("delta", {}),
                }
            except Exception as exc:  # noqa: BLE001 — a stale graph is not a failed release
                graph_update = {"failed": str(exc)}

        return {
            "build_result": result.model_dump(),
            "release": {"id": release_id, "environment": target_environment},
            "graph_update": graph_update,
            "status": "completed",
        }

    return {
        "requirements_intake": requirements_intake,
        "requirements_synthesis": requirements_synthesis,
        "ambiguity_check": ambiguity_check,
        "gate_1": gate_1,
        "design_proposal": design_proposal,
        "gate_2": gate_2,
        "test_case_generation": test_case_generation,
        "implementation": implementation,
        "qa_execution": qa_execution,
        "gate_3": gate_3,
        "release": release,
    }
