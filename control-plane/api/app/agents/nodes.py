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
from app.agents.handoff import build_task
from app.ports.design_agent import (
    DesignAgent,
    DesignProposal,
    DesignRequest,
)
from app.ports.qa_agent import QARequest
from app.ports.implementation_agent import (
    ImplementationRequest,
    ImplementationResult,
)
from app.core.change_review import review as review_change
from app.core.design_review import MAX_FILES as MAX_DESIGN_FILES
from app.core.design_review import assess_change
from app.core.seeding import refresh as refresh_index
from app.core.design_review import review as review_design
from app.core.impact import roll_up
from app.core.qa_coverage import reconcile as reconcile_coverage
from app.core.seeding import CODE_SYSTEM
from app.graph.paths import canonical as canonical_path
from app.graph.projects import DEFAULT_PROJECT, scoped
from app.core.context_graph import Assertion, ContextGraphStore, NodeSpec
from app.core.dispatches import DispatchStore
from app.core.gate_controller import GateController
from app.core.reliability import with_retry_fallback
from app.ports.build_deploy import BuildDeploy, DeployRequest
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
    implementation_agent: str = "inline",
    implementation_dispatch: WorkDispatch | None = None,
    dispatch_store: DispatchStore,
    context_graph: ContextGraphStore,
    llm_provider: LLMProvider,  # unused by stub logic this phase; wired for later phases
    audit_logger: AuditLogger,
    gate_controller: GateController,
    max_retries: int,
    design_attempts: int = DEFAULT_DESIGN_ATTEMPTS,
    # Defaults to this platform's own agent. A client substitutes one here
    # rather than forking the phase.
    design_agent: DesignAgent | None = None,
    implementation_agent_port: Any = None,
    qa_agent: Any = None,
    design_dispatch: WorkDispatch | None = None,
    dispatch_timeout_seconds: int = 1800,
    dispatch_provider: str = "local",
    target_repo: str = "",
    target_ref: str = "main",
    target_environment: str = "staging",
) -> dict[str, NodeFn]:
    # The default is this platform's own agent. Resolved here rather than in
    # the signature so a caller that supplies nothing gets the shipped
    # behaviour, and a client's adapter is a substitution at one place.
    if design_agent is None:
        from app.adapters.design_agent.inline import InlineDesignAgent

        design_agent = InlineDesignAgent(llm_provider)

    if qa_agent is None:
        # Follows the configured execution target, matching the registry.
        # A default that ignored it would read a payload the configured
        # provider never produces.
        if dispatch_provider in ("local", "local-pipeline"):
            from app.adapters.qa_agent.local import LocalQAAgent

            qa_agent = LocalQAAgent(provider=dispatch_provider)
        else:
            from app.adapters.qa_agent.dispatched import DispatchedQAAgent

            qa_agent = DispatchedQAAgent(provider=dispatch_provider)

    if implementation_agent_port is None:
        # Follows the configured agent, not a fixed default. The two arms
        # are different adapters: the inline one writes edits and is
        # reviewed before anything exists, the dispatched one interprets a
        # payload the reconciler brings back. Defaulting to inline while the
        # phase runs the dispatched arm meant read_result raised.
        if implementation_agent == "inline":
            from app.adapters.implementation_agent.inline import (
                InlineImplementationAgent,
            )
            from app.agents.implementation import SYSTEM as IMPLEMENTATION_SYSTEM
            from app.agents.implementation import Implementation, build_prompt

            implementation_agent_port = InlineImplementationAgent(
                llm_provider=llm_provider,
                system_prompt=IMPLEMENTATION_SYSTEM,
                schema=Implementation,
                build_prompt=build_prompt,
            )
        else:
            from app.adapters.implementation_agent.dispatched import (
                DispatchedImplementationAgent,
            )

            implementation_agent_port = DispatchedImplementationAgent(
                provider=implementation_agent, dispatch=implementation_dispatch
            )

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

        project = state.get("project") or DEFAULT_PROJECT
        catalogue = await context_graph.module_catalogue(project)
        known_paths = await context_graph.module_paths(project)
        file_dependents = await context_graph.file_dependents(project)
        criteria = await context_graph.criteria(project)
        known_criteria = {c["id"] for c in criteria if c.get("id")}
        # How complete the graph behind those edges is. A design cannot be
        # meaningfully contained by a graph that dropped a fifth of the
        # codebase's imports, so the review is told and refuses.
        graph_quality = await context_graph.index_provenance(project)

        request = DesignRequest(
            run_id=state["run_id"],
            project=project,
            # The snapshot the catalogue came from. A proposal that cannot
            # name it cannot be replayed, and "why did it choose that
            # module" stops being answerable the moment the graph moves.
            graph_commit=graph_quality.get("commit_sha") or "",
            requirement=requirement,
            criteria=criteria,
            catalogue=catalogue,
            context_snippets=snippets,
            max_files=MAX_DESIGN_FILES,
        )

        reasons: list[str] = []
        proposal = None
        for attempt in range(1, design_attempts + 1):
            outcome = await design_agent.propose(
                request.model_copy(update={"rejected_reasons": reasons})
            )

            if outcome.state == "pending":
                # A client's agent that works elsewhere. Parked on the same
                # seam CI uses, so an hour-long design survives a restart.
                # Only one attempt is possible in this shape: a retry would
                # mean a second dispatch, and the reasons a human needs are
                # better read on the rejected proposal than burned on another
                # agent run.
                proposal = await _await_design(state, outcome)
                if proposal is None:
                    return {
                        "design_proposal": {"failed": "the design agent produced nothing"},
                        "status": "design_rejected",
                    }
            else:
                proposal = outcome.proposal or DesignProposal()

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
            if outcome.state == "pending":
                break  # see above: no second dispatch

        return {
            "design_proposal": {
                **(proposal.model_dump() if proposal else {}),
                "rejected": reasons,
                "attempts": design_attempts,
            },
            "status": "design_rejected",
        }

    async def _await_design(state: dict[str, Any], outcome) -> DesignProposal | None:
        """Dispatch a design to a client's agent and wait for it.

        The same machinery the implementation and QA phases use: one row per
        run and phase, a deadline, and a reconciler that resumes the graph
        when the provider answers.
        """
        run_id = state["run_id"]
        provider = outcome.provider or "design-agent"

        claimed = await dispatch_store.claim(
            run_id, "design", provider, dispatch_timeout_seconds
        )
        if claimed is not None and design_dispatch is not None:
            try:
                handle = await design_dispatch.trigger(
                    run_id, "design", claimed.correlation_id, outcome.dispatch_inputs or {}
                )
                await dispatch_store.attach_external(
                    claimed.id, handle.external_id, handle.external_url
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a failed dispatch
                await dispatch_store.resolve(
                    claimed.id,
                    DispatchResult(state="failed", detail=f"could not start: {exc}"),
                )

        result = await gate_controller.request_external(
            state, "design", {"type": "design_handoff", "phase": "design", "agent": provider}
        )
        if result.get("state") != "succeeded":
            return None
        return design_agent.read_result(result.get("payload") or {})

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
        """Get the change written, review it deterministically, propose it.

        Two shapes, one review. An in-process agent returns edits and can be
        refused before they reach a branch. A client's cloud agent works
        elsewhere and opens its own pull request, so containment there is
        detection rather than prevention — the branch exists whatever the
        verdict, and a refusal fails the run with it left for a human.

        The review is the load-bearing part either way. An agent that edits a
        module the design never mentioned is not implementing the design, and
        the context graph is what makes that checkable rather than a matter of
        opinion. That it applies unchanged to an agent nobody here wrote is
        the point of putting it after the work rather than inside it.
        """
        design = state.get("design_proposal") or {}
        allowed = [c for c in design.get("modules", []) if c]

        if implementation_agent != "inline":
            return await _hand_off(state, design, allowed)

        candidate_paths = [p for p in design.get("files", []) if p]
        files = (
            await source_control.read_files(target_repo, target_ref, candidate_paths)
            if candidate_paths
            else {}
        )

        project = state.get("project") or DEFAULT_PROJECT
        outcome = await implementation_agent_port.implement(
            ImplementationRequest(
                run_id=state["run_id"],
                project=project,
                requirement=state.get("raw_input", {}).get("text", ""),
                design_summary=design.get("summary", ""),
                allowed_files=candidate_paths,
                sources=files,
                allowed_modules=allowed,
                criteria=await context_graph.criteria(project),
                repo=target_repo,
                base_ref=target_ref,
            )
        )
        # An inline agent never parks. Branching on the state rather than on
        # which agent is configured is what stops this phase growing an arm
        # per client.
        proposal = outcome.result or ImplementationResult()

        if proposal.blocked:
            return {
                "implementation": {"blocked": proposal.blocked, "summary": proposal.summary},
                "status": "implementation_blocked",
            }

        edits = [{"path": e.path, "content": e.content} for e in proposal.edits]
        known = await context_graph.module_paths(state.get("project") or DEFAULT_PROJECT)
        verdict = review_change(edits, allowed_modules=allowed, known_modules=known)

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

        return _accepted(state, proposal.summary, change, verdict.modules)

    async def _hand_off(
        state: dict[str, Any], design: dict[str, Any], allowed: list[str]
    ) -> dict[str, Any]:
        """Give the work to an agent this platform does not run, then wait.

        The same dispatch machinery the QA phase uses: one row per run and
        phase, a deadline, and a reconciler that resumes the graph when the
        provider answers. Reusing it rather than inventing a second waiting
        mechanism is what makes a two-hour agent run survive a restart.
        """
        run_id = state["run_id"]
        project = state.get("project") or DEFAULT_PROJECT
        task = build_task(
            requirement=(state.get("raw_input") or {}).get("text", ""),
            design=design,
            criteria=await context_graph.criteria(project),
            run_id=run_id,
        )

        # Through the port. What the agent is given is now a typed request
        # rather than three keys in a dict, and the inputs the dispatch is
        # started with come from the adapter that knows the agent — not from
        # this phase guessing at them.
        outcome = await implementation_agent_port.implement(
            ImplementationRequest(
                run_id=run_id,
                project=project,
                requirement=(state.get("raw_input") or {}).get("text", ""),
                brief=task,
                design_summary=design.get("summary", ""),
                allowed_files=allowed,
                allowed_modules=allowed,
                criteria=await context_graph.criteria(project),
                repo=target_repo,
                base_ref=target_ref,
            )
        )

        claimed = await dispatch_store.claim(
            run_id, "implementation", implementation_agent, dispatch_timeout_seconds
        )
        if claimed is not None:
            try:
                handle = await implementation_dispatch.trigger(
                    run_id,
                    "implementation",
                    claimed.correlation_id,
                    outcome.dispatch_inputs
                    or {"prompt": task, "base_ref": target_ref, "repo": target_repo},
                )
                await dispatch_store.attach_external(
                    claimed.id, handle.external_id, handle.external_url
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a failed dispatch
                await dispatch_store.resolve(
                    claimed.id,
                    DispatchResult(state="failed", detail=f"could not start: {exc}"),
                )

        result = await gate_controller.request_external(
            state,
            "implementation",
            {"type": "implementation_handoff", "phase": "implementation",
             "agent": implementation_agent},
        )

        if result.get("state") != "succeeded":
            return {
                "implementation": {
                    "agent": implementation_agent,
                    "failed": result.get("detail") or result.get("state"),
                },
                "status": "implementation_failed",
            }

        # Interpreted by the adapter that knows the provider, rather than
        # by untyped key reads here. read_result is the reconciler-safe half
        # of the port: a two-hour agent run is resumed after a restart with
        # nothing but this payload.
        finished = implementation_agent_port.read_result(result.get("payload") or {})
        head_ref = finished.head_ref
        base_ref = finished.base_ref or target_ref
        if not head_ref:
            return {
                "implementation": {
                    "agent": implementation_agent,
                    "failed": "the agent reported success but named no branch",
                },
                "status": "implementation_failed",
            }

        # Read what it actually did. Everything up to here is the agent's
        # account of itself; this is the repository's.
        try:
            written = await source_control.change_files(target_repo, base_ref, head_ref)
        except Exception as exc:  # noqa: BLE001
            return {
                "implementation": {
                    "agent": implementation_agent,
                    "branch": head_ref,
                    "failed": f"could not read the branch it produced: {exc}",
                },
                "status": "implementation_failed",
            }

        edits = [{"path": e.path, "content": e.content} for e in written]
        known = await context_graph.module_paths(state.get("project") or DEFAULT_PROJECT)
        verdict = review_change(edits, allowed_modules=allowed, known_modules=known)

        if not verdict.allowed:
            return {
                "implementation": {
                    "agent": implementation_agent,
                    "branch": head_ref,
                    "url": finished.url or None,
                    "files": [e["path"] for e in edits],
                    "rejected": verdict.reasons,
                    # Said explicitly because it is the difference between the
                    # two agent shapes: this branch was not prevented, it was
                    # caught, and it is still sitting in the repository.
                    "note": (
                        "the branch exists and was not merged — an agent that runs "
                        "elsewhere cannot be stopped before it writes"
                    ),
                },
                "status": "implementation_rejected",
            }

        change = ChangeRef(
            provider=implementation_agent,
            branch=head_ref,
            commit=finished.head_sha or None,
            base_commit=finished.base_sha or None,
            url=finished.url or None,
            number=finished.pull_request_id or None,
            files=[e["path"] for e in edits],
        )
        return _accepted(state, design.get("summary", ""), change, verdict.modules)

    def _accepted(
        state: dict[str, Any], summary: str, change: ChangeRef, modules: list[str]
    ) -> dict[str, Any]:
        return {
            "implementation": {
                "summary": summary,
                "files": change.files,
                "modules": modules,
                "branch": change.branch,
                "url": change.url,
                "commit": change.commit,
                "base_commit": change.base_commit,
                "agent": implementation_agent,
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
        project = state.get("project") or DEFAULT_PROJECT
        changed_paths = state.get("changed_paths", [])

        # How far the change reaches, decided here and handed down. The
        # design gate ran the same engine over the same edges earlier in this
        # run; a provider deriving its own would be the second answer to a
        # question already settled.
        module_paths = await context_graph.module_paths(project)
        path_to_module = {
            path: module for module, paths in module_paths.items() for path in paths
        }
        assessment = assess_change(
            changed_paths,
            await context_graph.file_dependents(project),
            known=set(path_to_module),
        )
        # Rolled up to modules for the obligation, kept at file level in the
        # assessment. `test_obligations` rather than `affected`: a
        # relationship can propagate impact without obliging a scenario, and
        # demanding coverage for a deployment edge would make the obligation
        # something teams learn to ignore.
        required_coverage = roll_up(assessment.test_obligations, path_to_module)

        qa_outcome = await qa_agent.execute(
            QARequest(
                run_id=run_id,
                project=project,
                base_sha=state.get("base_sha", ""),
                head_sha=head_sha,
                branch=(state.get("implementation") or {}).get("branch", ""),
                repo=target_repo,
                changed_paths=changed_paths,
                impact=assessment.as_dict(),
                required_coverage=required_coverage,
                criteria=await context_graph.criteria(project),
            )
        )
        if qa_outcome.state == "failed":
            return {
                "qa_result": {"state": "failed", "detail": qa_outcome.detail},
                "status": "qa_failed",
            }

        claimed = await dispatch_store.claim(
            run_id, "qa", dispatch_provider, dispatch_timeout_seconds
        )
        if claimed is not None:
            try:
                handle = await work_dispatch.trigger(
                    run_id,
                    "qa",
                    claimed.correlation_id,
                    qa_outcome.dispatch_inputs,
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

        # Interpreted by the provider's adapter rather than by untyped key
        # reads here. read_result is the reconciler-safe half of the port: a
        # QA run outlives the request that started it.
        proven = qa_agent.read_result(result.get("payload") or {})

        # Which criterion each scenario covers and which script ran it are
        # graph edges, so they are written here rather than by any separate
        # ingestion job — and they carry the run that asserted them.
        edges_written = await context_graph.ingest(
            run_id, "qa", _assertions_from({"assertions": proven.assertions})
        )

        # "Everything I ran passed" and "everything that needed running ran"
        # are different claims. A provider that cannot report coverage leaves
        # the second one unevaluated, and that is recorded rather than read
        # as full coverage.
        reports_coverage = bool(qa_agent.capabilities().get("reports_coverage"))

        # The half of the handover that does not move. A provider decides how
        # to test and may decide to cover less than the blast radius obliged
        # — but the difference is computed here, by ordinary code, so
        # covering less is a disclosure rather than a silence. Without this
        # the obligation is advice, and a provider returning passed=True ends
        # the conversation.
        coverage = reconcile_coverage(
            required_coverage,
            proven.covered_modules,
            proven.uncovered_modules,
            reports_coverage=reports_coverage,
        )

        return {
            "qa_result": {
                **result,
                "passed": proven.passed,
                "evidence_ref": proven.evidence_ref,
                "covered_criteria": proven.covered_criteria,
                "uncovered_criteria": proven.uncovered_criteria,
                "coverage_evaluated": reports_coverage,
                # What the change was judged to reach, and what QA settled
                # for. Carried into gate 3 because "the tests passed" and
                # "the tests covered what this change could break" are the
                # two halves of a release decision, and only the first one
                # is visible in a green tick.
                "required_coverage": required_coverage,
                "coverage_reconciliation": coverage.as_dict(),
                "impact_engine_version": assessment.engine_version,
            },
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
        project = state.get("project") or DEFAULT_PROJECT
        outcome = await build_deploy.deploy(
            DeployRequest(
                run_id=state["run_id"],
                environment=target_environment,
                revision=state.get("head_sha") or "",
                branch=implementation.get("branch", ""),
                project=project,
            )
        )
        if outcome.state == "failed" or outcome.deployment is None:
            # A dispatched deployment parks the run rather than pretending
            # to have finished. Not yet reachable — no adapter here
            # dispatches — but branching on the state rather than on which
            # adapter is configured is what stops the phase growing an arm
            # per platform.
            return {
                "status": "release_failed",
                "release": {"detail": outcome.detail or "deployment did not complete"},
            }
        deployment = outcome.deployment
        result = deployment

        # Scoped, like every other writer. Unscoped, these nodes landed in
        # the default project's graph while the index had populated
        # `code@<project>` — so the release's CONTAINS edges pointed at files
        # that did not exist in the project being released, and traceability
        # from a release back to a file was broken for every non-default
        # engagement.
        code_system = scoped(CODE_SYSTEM, project)
        pipeline_system = scoped("pipeline", project)

        release_id = f"{state['run_id'][:8]}"
        release_node = NodeSpec("RELEASE", pipeline_system, release_id, {
            "build_id": deployment.artifact.build_id,
            "branch": implementation.get("branch", ""),
            # The artifact, not the job. "What is running in staging" is a
            # question about a digest; a release that records only the build
            # id describes the thing that made it.
            "artifact": deployment.artifact.reference,
            "artifact_digest": deployment.artifact.digest,
            "revision": deployment.revision,
            "deployment_id": deployment.deployment_id,
            "deployment_url": deployment.url,
            # None rather than False when the adapter cannot tell. A release
            # gate reading False would be acting on a check nobody ran.
            "healthy": deployment.healthy,
        })
        assertions = [
            Assertion(
                "CONTAINS",
                release_node,
                NodeSpec("SOURCE_ARTIFACT", code_system, canonical_path(path), {}),
            )
            for path in implementation.get("files", [])
        ]
        assertions.append(
            Assertion(
                "DEPLOYED_TO",
                release_node,
                NodeSpec("ENVIRONMENT", pipeline_system, target_environment, {}),
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
            "deployment": deployment.model_dump(),
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
