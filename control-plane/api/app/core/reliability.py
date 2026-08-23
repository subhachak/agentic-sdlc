"""Retry + fallback-to-template reliability wrapper for business-logic nodes
ONLY. Gate nodes are never wrapped with this — a paused-for-human node isn't
a transient failure to retry, and auto-falling-back a gate would silently
violate "humans approve at every phase boundary."

Composition order matters: `audited(...)` wraps `with_retry_fallback(...)`
wraps the core node function, so audit sits outermost — exactly one
before/after audit pair is written per logical node call, regardless of how
many retries happened underneath.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
FallbackFactory = Callable[[dict[str, Any]], dict[str, Any]]


def with_retry_fallback(
    node_name: str, fallback_factory: FallbackFactory, max_retries: int
) -> Callable[[NodeFn], NodeFn]:
    def decorator(fn: NodeFn) -> NodeFn:
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            for attempt in range(max_retries + 1):
                try:
                    return await fn(state)
                except Exception as exc:  # noqa: BLE001 - any node failure falls back, never crashes the graph
                    logger.warning(
                        "node %s failed on attempt %d/%d: %s",
                        node_name,
                        attempt + 1,
                        max_retries + 1,
                        exc,
                    )
            fallback = fallback_factory(state)
            fallback["_reliability_fallback_used"] = True
            return fallback

        return wrapper

    return decorator
