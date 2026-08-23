"""Port: where the pipeline gets its raw requirement input from.

Demo adapter: plain text/CSV input. Future: Jira, Confluence, ADO.
"""

from typing import Literal, Protocol

from pydantic import BaseModel


class RequirementsInput(BaseModel):
    text: str | None = None
    file_bytes: bytes | None = None
    filename: str | None = None


class RequirementsDoc(BaseModel):
    text: str
    source_type: Literal["text", "csv"]
    item_count: int


class RequirementsSource(Protocol):
    async def fetch(self, raw: RequirementsInput) -> RequirementsDoc: ...
