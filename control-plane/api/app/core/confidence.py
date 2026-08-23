"""Confidence scoring — stub for this phase.

Returns a fixed placeholder score. The interface already reflects the
governance rule that matters: an agent-proposed value is never "confirmed"
until a human explicitly confirms it, and unconfirmed values must be
EXCLUDED from any aggregate — never defaulted to zero or silently guessed.
"""

from datetime import datetime, timezone

from pydantic import BaseModel

PLACEHOLDER_SCORE = 0.75


class ConfidenceEntry(BaseModel):
    node_name: str
    score: float
    confirmed: bool = False
    confirmed_at: datetime | None = None


def score_placeholder(node_name: str) -> ConfidenceEntry:
    """Stub scorer: always returns the fixed placeholder score, unconfirmed."""
    return ConfidenceEntry(node_name=node_name, score=PLACEHOLDER_SCORE, confirmed=False)


def confirm(entry: ConfidenceEntry) -> ConfidenceEntry:
    """The only way a value becomes 'confirmed' — an explicit human action."""
    return entry.model_copy(update={"confirmed": True, "confirmed_at": datetime.now(timezone.utc)})


def aggregate_confidence(entries: list[ConfidenceEntry]) -> float | None:
    """Average of CONFIRMED entries only. None (not 0.0) if none are confirmed —
    an aggregate over zero confirmed values is undefined, not zero.
    """
    confirmed = [e.score for e in entries if e.confirmed]
    if not confirmed:
        return None
    return sum(confirmed) / len(confirmed)
