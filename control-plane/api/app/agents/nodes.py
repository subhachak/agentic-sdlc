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
from app.core.context_graph import Assertion, ContextGraphStore, NodeSpec
from app.core.dispatches import DispatchStore
from app.core.gate_controller import GateController
from app.core.reliability import with_retry_fallback
from app.ports.build_deploy import BuildDeploy
from app.ports.code_design_context import CodeDesignContext
from app.ports.llm_provider import LLMProvider
from app.ports.requirements_source import RequirementsInput, RequirementsSource
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


def build_nodes(
    *,
    requirements_source: RequirementsSource,
    code_design_context: CodeDesignContext,
    test_management: TestManagement,
    build_deploy: BuildDeploy,
    work_dispatch: WorkDispatch,
    dispatch_store: DispatchStore,
    context_graph: ContextGraphStore,
    llm_provider: LLMProvider,  # unused by stub logic this phase; wired for later phases
    audit_logger: AuditLogger,
    gate_controller: GateController,
    max_retries: int,
    dispatch_timeout_seconds: int = 1800,
    dispatch_provider: str = "local",
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
        query = (state.get("requirements_synthesis") or {}).get("summary", "")
        snippets = await code_design_context.retrieve_context(query)
        proposal = {
            "summary": "stub design proposal grounded in retrieved context",
            "context_snippets": [s.model_dump() for s in snippets],
        }
        return {"design_proposal": proposal, "status": "awaiting_gate_2"}

    async def gate_2(state: dict[str, Any]) -> dict[str, Any]:
        payload = {"type": "design_approval", "design_proposal": state.get("design_proposal")}
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

    async def qa_execution(state: dict[str, Any]) -> dict[str, Any]:
        """Hand the QA phase to whatever actually runs it, then park.

        Deliberately not wrapped in `with_retry_fallback`, for the same
        reason gate nodes are not: a parked node is not a transient failure,
        and falling back would mean reporting a QA verdict that no test
        produced. Retries belong inside the adapter's HTTP calls, where a
        flaky response genuinely is transient.
        """
        run_id = state["run_id"]

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
                        "head_sha": state.get("head_sha", ""),
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

    @business("build_deploy_stub", fallback={"status": "build_deploy_failed"})
    async def build_deploy_stub(state: dict[str, Any]) -> dict[str, Any]:
        result = await build_deploy.trigger_build(
            state["run_id"], {"test_case_count": len(state.get("test_cases", []))}
        )
        return {"build_result": result.model_dump(), "status": "completed"}

    return {
        "requirements_intake": requirements_intake,
        "requirements_synthesis": requirements_synthesis,
        "ambiguity_check": ambiguity_check,
        "gate_1": gate_1,
        "design_proposal": design_proposal,
        "gate_2": gate_2,
        "test_case_generation": test_case_generation,
        "qa_execution": qa_execution,
        "gate_3": gate_3,
        "build_deploy_stub": build_deploy_stub,
    }
