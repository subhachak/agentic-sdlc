"""A ResultPublisher that writes nothing anywhere.

For a run with no review thread to post to — a nightly regression, a local
pipeline, an air-gapped deployment. It reports honestly that it published
nothing rather than pretending, so the gate records "not filed" instead of
reading silence as success.
"""

from __future__ import annotations

from typing import Any

from orchestrator.ports_publish import PUBLISH_CONTRACT_VERSION, Destination


class SilentPublisher:
    contract_version = PUBLISH_CONTRACT_VERSION

    def capabilities(self) -> dict[str, Any]:
        return {"name": "silent", "comments": False, "raises_defects": False}

    def publish_verdict(self, destination: Destination, body: str) -> str:
        return ""

    def raise_defect(
        self, destination: Destination, title: str, body: str, labels: list[str]
    ) -> str:
        return ""
