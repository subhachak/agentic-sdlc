"""Central Gate Controller — owns ALL interrupt()/resume() logic. Gate nodes
call into this rather than each managing their own gate logic, so there is
exactly one place in the codebase that calls `interrupt()`.

A pause is not always a human one. `request_external` parks a run on a
remote execution instead of a person: same mechanism, different resumer.
Keeping both here is what preserves the single-interrupt-site rule.

This module is part of the deterministic core: it never imports an LLM
client, directly or transitively.
"""

from typing import Any

from langgraph.types import interrupt

from app.core.audit import AuditLogger


class GateController:
    def __init__(self, logger: AuditLogger):
        self._logger = logger

    async def request_gate(
        self, state: dict[str, Any], gate_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Pause the graph for human approval, or auto-approve if configured to.

        Writes its own audit entries directly (not the generic @audited node
        wrapper — see core/audit.py) because a gate's "after" entry carries a
        human_decision the generic wrapper has no way to know.

        LangGraph re-executes a node's coroutine from its start on resume —
        there is no way to suspend mid-function across process boundaries —
        so any code before `interrupt()` runs again on the resume pass. The
        `has_written` dedupe guard is what keeps the gate's "before" entry to
        exactly one row despite that: the resume pass sees it already exists
        and skips the second write. `write_after` never needs the same guard
        because it only runs once `interrupt()` has actually returned a
        decision, which happens on at most one of the (pause, resume) calls.
        """
        run_id = state["run_id"]
        config = state["config"]

        if not await self._logger.has_written(run_id, gate_name, "before"):
            await self._logger.write_before(run_id, gate_name, payload)

        if config.auto_approve_gates:
            decision: dict[str, Any] = {"approved": True, "feedback": None}
        else:
            decision = interrupt(payload)

        await self._logger.write_after(
            run_id,
            gate_name,
            payload,
            {"decision": decision},
            human_decision="approved" if decision.get("approved") else "rejected",
        )
        return decision

    async def request_external(
        self, state: dict[str, Any], node_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Pause the graph until a remote execution reports back.

        Unlike `request_gate` this ignores `auto_approve_gates`. That flag
        exists so a headless run does not stop for a human; it cannot
        manufacture the result of a job that has not run.

        The same `has_written` dedupe applies for the same reason: LangGraph
        re-executes the node from its start on resume, so the "before" entry
        would otherwise be written twice. The far more dangerous side effect
        on that second pass — triggering a second remote job — is guarded
        separately, by the unique constraint in core/dispatches.py.
        """
        run_id = state["run_id"]

        if not await self._logger.has_written(run_id, node_name, "before"):
            await self._logger.write_before(run_id, node_name, payload)

        result = interrupt(payload)

        await self._logger.write_after(
            run_id,
            node_name,
            payload,
            {"result": result},
            human_decision=None,
        )
        return result
