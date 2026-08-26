"""Which version of a thing a statement was true about.

Node identity is stable on purpose: a file rewritten at a new commit is the
same file, and making every revision its own node would multiply the graph
by history and break every query that means "this file".

But evidence is *about* a revision. A TEST_RUN that passed against
`app/pay.ts` as it stood at abc123 says nothing about the same path at
def456 — and with identity alone the graph could not tell the difference, so
a criterion stayed "verified" across a rewrite that removed the behaviour
being verified. `CodeFile` already carried the `sha256` that answers this;
nothing used it.

So the revision travels on the *assertion*, not the node. An edge records
what it was observed against, and a consumer can ask whether that still
matches — which is the whole question: is this evidence about the thing that
is here now.

Deliberately opaque. A commit sha, a content hash, an ETag, a Jira updated
timestamp — whatever the source uses to mean "this version". Compared for
equality only, so its format stays the source's business.
"""

from __future__ import annotations

from typing import Any

# Attribute key on an edge. One name, so a consumer never has to know which
# phase wrote the edge to find out what it was about.
REVISION = "observed_at_revision"


def stamped(attributes: dict[str, Any] | None, revision: str | None) -> dict[str, Any]:
    """Attach the revision an assertion was observed against.

    A revision of None leaves the attributes alone rather than writing an
    empty string: "not recorded" and "recorded as nothing" are different,
    and only the first is honest about a provider that could not say.
    """
    out = dict(attributes or {})
    if revision:
        out[REVISION] = revision
    return out


def revision_of(attributes: dict[str, Any] | None) -> str | None:
    return (attributes or {}).get(REVISION) or None


def is_stale(attributes: dict[str, Any] | None, current: str | None) -> bool | None:
    """Whether this statement was made about something that has since moved.

    Three answers, not two. `None` means unknowable — either the assertion
    never recorded a revision or the caller cannot say what the current one
    is — and a caller that treated that as "fresh" would be reading silence
    as evidence, which is the failure this module exists to prevent.
    """
    observed = revision_of(attributes)
    if not observed or not current:
        return None
    return observed != current
