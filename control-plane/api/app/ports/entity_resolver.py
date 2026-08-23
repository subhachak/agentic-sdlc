"""Port: turn a native identifier in a client system into a graph identity.

This is the seam that makes one fixed ontology work across every client
stack. The ontology says what an ACCEPTANCE_CRITERION is; the adapter knows
that in this client it is a Jira sub-task, and in the next one a row in a
requirements spreadsheet.

Demo adapter: a local resolver that trusts what it is given. Future: Jira,
GitHub, Zephyr, ServiceNow — one per system of record, each able to enrich
the projection and to fail when the thing does not exist.
"""

from typing import Any, Protocol

from pydantic import BaseModel, Field


class NodeRef(BaseModel):
    id: str
    type: str
    system: str
    external_id: str
    projection: dict[str, Any] = Field(default_factory=dict)


class EntityResolver(Protocol):
    async def resolve(
        self,
        node_type: str,
        system: str,
        external_id: str,
        projection: dict[str, Any] | None = None,
    ) -> NodeRef: ...
