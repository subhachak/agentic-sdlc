"""Watches remote executions and feeds their results back into paused runs.

One background task for the whole process, not one per run, so its
concurrency behaviour stays something you can reason about. Each tick does
two independent things:

  1. asks the WorkDispatch port what happened to every pending dispatch,
     and gives up on any that has passed its deadline;
  2. resumes the graph for every dispatch that has a result the run has not
     consumed yet.

They are separate on purpose. A result is always persisted before any
resume is attempted, so a job that finishes before its graph thread has
parked is queued rather than lost.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from collections.abc import Callable
from typing import Any

from langgraph.types import Command

from app.core.dispatches import DispatchStore
from app.core.graph_runtime import spawn_run
from app.ports.work_dispatch import DispatchResult, WorkDispatch

logger = logging.getLogger(__name__)


Dispatchers = Mapping[str, WorkDispatch]


def _for(dispatchers: Dispatchers | WorkDispatch, provider: str) -> WorkDispatch | None:
    """The adapter that started this dispatch, not whichever one is current.

    Phases no longer share a provider: QA may run in GitHub Actions while the
    implementation is handed to a cloud coding agent, and a row started by one
    cannot be polled by the other — its external id means nothing there. The
    row records who started it, so that is who is asked.
    """
    if isinstance(dispatchers, Mapping):
        return dispatchers.get(provider)
    return dispatchers  # a single adapter, from before phases could differ


async def poll_pending(dispatchers: Dispatchers | WorkDispatch, store: DispatchStore) -> int:
    """Resolve whatever has finished. Returns how many moved off pending."""
    resolved = 0
    for row in await store.list_pending():
        if row.is_overdue:
            await store.resolve(
                row.id,
                DispatchResult(state="timed_out", detail="deadline passed with no result"),
            )
            resolved += 1
            continue

        work_dispatch = _for(dispatchers, row.provider)
        if work_dispatch is None:
            # Configuration changed under a live dispatch. Failing it is the
            # only honest outcome: nothing here can ask a provider that is no
            # longer configured how a job it started is going.
            await store.resolve(
                row.id,
                DispatchResult(
                    state="failed",
                    detail=f"no adapter configured for provider {row.provider!r}; "
                           f"this dispatch was started under a different configuration",
                ),
            )
            resolved += 1
            continue

        try:
            result = await work_dispatch.check(row.to_handle())
        except Exception as exc:  # noqa: BLE001 - a flaky provider must not kill the loop
            logger.warning("dispatch %s: check failed: %s", row.id, exc)
            continue

        if result.external_id and not row.external_id:
            await store.attach_external(row.id, result.external_id, result.external_url)

        if result.state != "pending":
            await store.resolve(row.id, result)
            resolved += 1

    return resolved


async def apply_results(graph: Any, active_tasks: dict, store: DispatchStore) -> int:
    """Resume every run whose result is still unconsumed."""
    applied = 0
    for row in await store.list_unapplied():
        payload = row.to_resume_payload()
        # False means the thread is still busy — most likely it has not
        # reached its interrupt() yet. Leave the row for the next tick.
        if spawn_run(active_tasks, graph, row.run_id, Command(resume=payload)):
            await store.mark_applied(row.id)
            applied += 1
    return applied


async def tick(
    graph: Any,
    dispatchers: Dispatchers | WorkDispatch,
    active_tasks: dict,
    store: DispatchStore,
) -> tuple[int, int]:
    return await poll_pending(dispatchers, store), await apply_results(
        graph, active_tasks, store
    )


async def run_forever(
    provider: Callable[[], tuple[Any, WorkDispatch, dict, DispatchStore]],
    interval_seconds: float,
) -> None:
    """`provider` is called every tick rather than captured once.

    Configuration can be changed through the control plane, which rebuilds the
    adapters and the graph. A reconciler holding references from start-up would
    quietly keep polling the provider the operator just switched away from.
    """
    while True:
        try:
            await tick(*provider())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must outlive any single failure
            logger.exception("reconciler tick failed")
        await asyncio.sleep(interval_seconds)
