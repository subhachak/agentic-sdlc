"""Demo-default resolver: derives identity, trusts the projection it is given.

A real adapter would call the source system to confirm the thing exists and
to build the projection from it. This one exists so the graph works with no
external dependency, and so identity behaviour can be tested without one.
"""

from __future__ import annotations

from typing import Any

from app.graph.identity import node_id
from app.graph.ontology import validate_node_type
from app.ports.entity_resolver import NodeRef


class LocalEntityResolver:
    async def resolve(
        self,
        node_type: str,
        system: str,
        external_id: str,
        projection: dict[str, Any] | None = None,
    ) -> NodeRef:
        validate_node_type(node_type)
        return NodeRef(
            id=node_id(node_type, system, external_id),
            type=node_type,
            system=system,
            external_id=external_id,
            projection=projection or {},
        )
