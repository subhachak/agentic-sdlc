"""Read requirements from Jira Cloud.

The second implementation of this port, and the reason it changed shape. An
issue is an identity, a revision and a set of curated fields — flattening it
into a paragraph throws away exactly what makes a system of record worth
integrating with.

Reads only. This adapter never writes to Jira: a platform that edits the
client's tracker as a side effect of a pipeline run is a platform nobody
installs twice. Pushing status back is a separate port and a separate
decision.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.ports.requirements_source import (
    AcceptanceCriterion,
    RequirementItem,
    RequirementsDoc,
    RequirementsInput,
    SourceProvenance,
    now,
)

ADAPTER_VERSION = "1.0.0"
MAX_RESULTS = 50
TIMEOUT = 30.0

# Fields whose name suggests the client keeps acceptance criteria there.
# Matched case-insensitively against the field's display name, because the
# custom field id differs per Jira instance and hardcoding customfield_10035
# is how an integration becomes one client's integration.
CRITERIA_FIELD_HINTS = ("acceptance criteria", "acceptance_criteria", "given/when/then")


class JiraRequirementsSource:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        default_query: str = "",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._email = email
        self._token = api_token
        self._default_query = default_query

    @property
    def _headers(self) -> dict[str, str]:
        # Basic auth with an API token is Atlassian's documented scheme for
        # Jira Cloud. Built per request and never logged.
        raw = f"{self._email}:{self._token}".encode()
        return {
            "Authorization": f"Basic {base64.b64encode(raw).decode()}",
            "Accept": "application/json",
        }

    async def fetch(self, raw: RequirementsInput) -> RequirementsDoc:
        """Freeform text still wins when it is given.

        Someone pasting a paragraph has said what they want more directly
        than any query would, and an intake that ignored it to run a JQL
        search would be answering a question nobody asked.
        """
        if raw.text and raw.text.strip():
            return RequirementsDoc(
                text=raw.text,
                source_type="text",
                item_count=1,
                provenance=self._provenance(),
            )

        ref = raw.ref
        if ref and ref.external_id:
            items = [await self._issue(ref.external_id)]
        else:
            query = (ref.query if ref else "") or self._default_query
            if not query:
                raise ValueError(
                    "nothing to fetch: give a requirement text, an issue key, or "
                    "configure JIRA_QUERY with a JQL filter"
                )
            items = await self._search(query)

        return RequirementsDoc(
            text=_as_prose(items),
            source_type="jira",
            item_count=len(items),
            items=items,
            provenance=self._provenance(),
        )

    def _provenance(self) -> SourceProvenance:
        return SourceProvenance(
            system="jira",
            instance=self._base,
            fetched_at=now(),
            adapter_version=ADAPTER_VERSION,
        )

    # ── transport ────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
                response = await client.get(
                    f"{self._base}{path}", headers=self._headers, params=params
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                # PermissionError and ValueError rather than httpx types: a
                # caller that had to catch httpx would be coupled to the fact
                # that this particular adapter speaks HTTP.
                raise PermissionError(
                    "Jira rejected the credentials — check JIRA_EMAIL and "
                    "JIRA_API_TOKEN, and that the token has Browse Projects"
                ) from exc
            if status == 404:
                raise ValueError(f"Jira has no such issue or filter: {path}") from exc
            if status == 429:
                raise RuntimeError("Jira rate-limited this request; retry later") from exc
            raise RuntimeError(f"Jira returned {status} for {path}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"could not reach Jira at {self._base}: {exc}") from exc

    async def check_access(self) -> dict[str, Any]:
        """Verify the credentials before a run depends on them.

        The same shape the work-dispatch adapters use, so the console can
        offer one "check" affordance rather than one per integration.
        """
        try:
            me = await self._get("/rest/api/3/myself")
        except (PermissionError, ValueError, RuntimeError) as exc:
            return {"ok": False, "detail": str(exc)}
        return {
            "ok": True,
            "detail": f"authenticated as {me.get('displayName') or me.get('emailAddress') or 'unknown'}",
        }

    async def _issue(self, key: str) -> RequirementItem:
        body = await self._get(
            f"/rest/api/3/issue/{key}",
            {"fields": "*navigable", "expand": "names"},
        )
        return self._to_item(body, body.get("names") or {})

    async def _search(self, jql: str) -> list[RequirementItem]:
        body = await self._get(
            "/rest/api/3/search",
            {
                "jql": jql,
                "maxResults": str(MAX_RESULTS),
                "fields": "*navigable",
                "expand": "names",
            },
        )
        names = body.get("names") or {}
        return [self._to_item(issue, names) for issue in body.get("issues") or []]

    # ── mapping ──────────────────────────────────────────────────────────

    def _to_item(self, issue: dict, names: dict[str, str]) -> RequirementItem:
        fields = issue.get("fields") or {}
        key = issue.get("key") or ""
        description = _flatten(fields.get("description"))
        criteria = _criteria_from(fields, names) or _criteria_from_text(description)

        parent = (fields.get("parent") or {}).get("key") or ""
        status = ((fields.get("status") or {}).get("name")) or ""

        return RequirementItem(
            external_id=key,
            title=fields.get("summary") or "",
            text=description,
            status=status,
            url=f"{self._base}/browse/{key}" if key else "",
            # Jira's own "this version" marker. Compared for equality only,
            # so its format is the source's business.
            revision=fields.get("updated") or "",
            parent_id=parent,
            labels=list(fields.get("labels") or []),
            criteria=criteria,
        )


def _criteria_from(fields: dict, names: dict[str, str]) -> list[AcceptanceCriterion]:
    """Acceptance criteria from whichever custom field the client uses.

    Located by display name rather than by field id. The id differs per
    instance, so hardcoding one would make this adapter work at exactly one
    customer.
    """
    for field_id, display in (names or {}).items():
        if not any(hint in (display or "").lower() for hint in CRITERIA_FIELD_HINTS):
            continue
        text = _flatten(fields.get(field_id))
        if text.strip():
            return _split(text)
    return []


def _criteria_from_text(description: str) -> list[AcceptanceCriterion]:
    """Fall back to the description's own list markers.

    Deliberately conservative: only lines that look like an enumerated or
    bulleted statement. Guessing harder would invent criteria the client
    never wrote, and an invented criterion becomes a test obligation and then
    a release gate.
    """
    lines = [line.strip() for line in description.splitlines()]
    marked = [
        line.lstrip("-*•0123456789.) ").strip()
        for line in lines
        if line.startswith(("-", "*", "•")) or (line[:2].rstrip(".)").isdigit() if line else False)
    ]
    return [AcceptanceCriterion(text=t) for t in marked if t]


def _split(text: str) -> list[AcceptanceCriterion]:
    parts = [
        line.lstrip("-*•0123456789.) ").strip()
        for line in text.splitlines()
        if line.strip()
    ]
    return [AcceptanceCriterion(text=p) for p in parts if p]


def _flatten(value: Any) -> str:
    """Atlassian Document Format, or a plain string, to text.

    ADF is a nested node tree. Walked rather than parsed with a library
    because the only thing needed here is the text, and adding a dependency
    to read one field is a dependency a client has to approve.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten(v) for v in value).strip()
    if not isinstance(value, dict):
        return str(value)

    node_type = value.get("type")
    if node_type == "text":
        return value.get("text") or ""
    if node_type == "hardBreak":
        return "\n"

    inner = _flatten(value.get("content"))
    # Block-level nodes end a line; inline nodes do not, or every word would
    # arrive on its own row.
    if node_type in ("paragraph", "heading", "listItem", "blockquote", "codeBlock"):
        return inner + "\n"
    if node_type in ("bulletList", "orderedList"):
        return "\n".join(
            f"- {line}" for line in inner.splitlines() if line.strip()
        ) + "\n"
    return inner


def _as_prose(items: list[RequirementItem]) -> str:
    """The flat view the synthesis agent reads.

    Structure is preserved in `items`; this is the same content rendered for
    a reader, so an agent grounded in prose and a gate reasoning over records
    are looking at one thing.
    """
    blocks = []
    for item in items:
        block = [f"{item.external_id}: {item.title}".strip(": ")]
        if item.status:
            block.append(f"Status: {item.status}")
        if item.text.strip():
            block.append(item.text.strip())
        if item.criteria:
            block.append("Acceptance criteria:")
            block.extend(f"- {c.text}" for c in item.criteria)
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)
