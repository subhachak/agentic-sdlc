"""The second implementation of RequirementsSource, and what it proved.

The port was `fetch(text | file) -> {text, source_type, item_count}` with
source_type a closed Literal["text","csv"]. Writing this adapter is what
showed the seam was a seam in name only: "jira" could not be expressed
without editing the port.

No network. Jira's payload shapes are pinned as fixtures, because the thing
worth testing is the mapping — ADF flattening, criteria discovery, identity
and revision — not httpx.
"""

from __future__ import annotations

import pytest

from app.adapters.requirements_source.jira import (
    JiraRequirementsSource,
    _as_prose,
    _flatten,
)
from app.ports.requirements_source import RequirementRef, RequirementsInput


def adf(*paragraphs: str) -> dict:
    """Atlassian Document Format, as Jira Cloud actually returns it."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ],
    }


ISSUE = {
    "key": "ACME-42",
    "names": {"customfield_10035": "Acceptance Criteria", "summary": "Summary"},
    "fields": {
        "summary": "Adjusters can filter claims by status",
        "description": adf("Adjusters see every claim and cannot narrow the list."),
        "status": {"name": "In Progress"},
        "updated": "2026-08-20T11:04:33.000+0000",
        "labels": ["claims", "ux"],
        "parent": {"key": "ACME-1"},
        "customfield_10035": adf(
            "- Filtering by open shows only open claims",
            "- Clearing the filter restores the full list",
        ),
    },
}


class FakeJira(JiraRequirementsSource):
    """Real mapping, canned transport."""

    def __init__(self, payloads: dict[str, dict]):
        super().__init__("https://acme.atlassian.net", "bot@acme.example", "token")
        self._payloads = payloads
        self.requested: list[str] = []

    async def _get(self, path: str, params=None):
        self.requested.append(path)
        if path not in self._payloads:
            raise ValueError(f"Jira has no such issue or filter: {path}")
        return self._payloads[path]


@pytest.mark.asyncio
async def test_an_issue_keeps_its_identity_and_revision():
    """A requirement the graph cannot trace back to its record stops
    traceability at the platform boundary."""
    source = FakeJira({"/rest/api/3/issue/ACME-42": ISSUE})
    doc = await source.fetch(RequirementsInput(ref=RequirementRef(external_id="ACME-42")))

    assert doc.source_type == "jira"
    item = doc.items[0]
    assert item.external_id == "ACME-42"
    assert item.url == "https://acme.atlassian.net/browse/ACME-42"
    assert item.status == "In Progress"
    # Opaque, compared for equality only — its format is Jira's business.
    assert item.revision == "2026-08-20T11:04:33.000+0000"
    assert item.parent_id == "ACME-1"
    assert item.labels == ["claims", "ux"]


@pytest.mark.asyncio
async def test_acceptance_criteria_come_from_the_field_the_client_uses():
    """Located by display name, not by field id. customfield_10035 differs
    per instance, so hardcoding one makes this one customer's integration."""
    source = FakeJira({"/rest/api/3/issue/ACME-42": ISSUE})
    doc = await source.fetch(RequirementsInput(ref=RequirementRef(external_id="ACME-42")))

    texts = [c.text for c in doc.items[0].criteria]
    assert texts == [
        "Filtering by open shows only open claims",
        "Clearing the filter restores the full list",
    ]


@pytest.mark.asyncio
async def test_criteria_are_not_invented_when_the_source_has_none():
    """An invented criterion becomes a test obligation and then a release
    gate. Silence is the honest answer."""
    bare = {
        "key": "ACME-9",
        "names": {},
        "fields": {
            "summary": "Tidy up the footer",
            "description": adf("It looks cramped on mobile."),
            "status": {"name": "To Do"},
            "updated": "2026-08-01T00:00:00.000+0000",
        },
    }
    source = FakeJira({"/rest/api/3/issue/ACME-9": bare})
    doc = await source.fetch(RequirementsInput(ref=RequirementRef(external_id="ACME-9")))
    assert doc.items[0].criteria == []


@pytest.mark.asyncio
async def test_a_jql_search_returns_every_matching_issue():
    source = FakeJira({"/rest/api/3/search/jql": {"names": ISSUE["names"], "issues": [ISSUE, ISSUE]}})
    doc = await source.fetch(
        RequirementsInput(ref=RequirementRef(external_id="", query="project = ACME"))
    )
    assert doc.item_count == 2


@pytest.mark.asyncio
async def test_pasted_text_beats_a_configured_query():
    """Someone pasting a paragraph has said what they want more directly than
    any filter would."""
    source = FakeJira({})
    doc = await source.fetch(RequirementsInput(text="Add a status filter."))
    assert doc.source_type == "text"
    assert source.requested == []


@pytest.mark.asyncio
async def test_asking_for_nothing_says_so_rather_than_guessing():
    source = FakeJira({})
    with pytest.raises(ValueError) as raised:
        await source.fetch(RequirementsInput())
    assert "issue key" in str(raised.value)


@pytest.mark.asyncio
async def test_the_fetch_records_where_it_came_from():
    """An intake that cannot say where it came from produces a requirement
    the audit trail cannot attribute."""
    source = FakeJira({"/rest/api/3/issue/ACME-42": ISSUE})
    doc = await source.fetch(RequirementsInput(ref=RequirementRef(external_id="ACME-42")))
    assert doc.provenance.system == "jira"
    assert doc.provenance.instance == "https://acme.atlassian.net"
    assert doc.provenance.fetched_at
    assert doc.provenance.adapter_version


def test_adf_flattens_to_readable_text():
    nested = {
        "type": "doc",
        "content": [
            {"type": "heading", "content": [{"type": "text", "text": "Goal"}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "one"}]}
                        ],
                    }
                ],
            },
        ],
    }
    out = _flatten(nested)
    assert "Goal" in out
    assert "- one" in out


def test_a_plain_string_description_still_works():
    """Jira Server and older Cloud APIs return a string, not ADF."""
    assert _flatten("just text") == "just text"
    assert _flatten(None) == ""


@pytest.mark.asyncio
async def test_the_prose_view_and_the_structured_view_agree():
    """The agent reads prose and the gates reason over records; they have to
    be the same content or the two halves of the platform disagree."""
    source = FakeJira({"/rest/api/3/issue/ACME-42": ISSUE})
    doc = await source.fetch(RequirementsInput(ref=RequirementRef(external_id="ACME-42")))

    assert doc.items[0].external_id in doc.text
    assert doc.items[0].title in doc.text
    for criterion in doc.items[0].criteria:
        assert criterion.text in doc.text


@pytest.mark.parametrize(
    "status,expected,fragment",
    [
        (401, PermissionError, "credentials"),
        (403, PermissionError, "credentials"),
        (404, ValueError, "no such issue"),
        (429, RuntimeError, "rate-limited"),
        (500, RuntimeError, "returned 500"),
    ],
)
@pytest.mark.asyncio
async def test_transport_failures_arrive_as_the_platform_s_own_errors(
    status, expected, fragment, monkeypatch
):
    """Not as httpx. A caller that had to catch httpx would be coupled to the
    fact that this particular adapter speaks HTTP — which is the coupling the
    port exists to prevent.

    Exercises the real _get, through a mocked transport: overriding _get
    would remove the translation being tested.
    """
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={})

    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    source = JiraRequirementsSource("https://acme.atlassian.net", "a@b.c", "token")
    with pytest.raises(expected) as raised:
        await source._get("/rest/api/3/myself")
    assert fragment in str(raised.value)


@pytest.mark.asyncio
async def test_check_access_answers_rather_than_raising(monkeypatch):
    """The console offers one "check" affordance per integration, and a
    connection test that throws is a connection test nobody can render."""
    import httpx

    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(401, json={})
        )
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    source = JiraRequirementsSource("https://acme.atlassian.net", "a@b.c", "bad")
    result = await source.check_access()
    assert result["ok"] is False
    assert "credentials" in result["detail"]


# ── what fixtures could not have told me ──────────────────────────────────


@pytest.mark.asyncio
async def test_check_access_probes_what_the_adapter_actually_does():
    """It probed /rest/api/3/myself, which needs a user-read scope a
    data-reading token legitimately does not carry. Against a real scoped
    token it reported "Jira rejected the credentials" for a configuration
    whose credentials were correct — a control that fails on a working
    setup, which sends someone re-minting tokens to fix nothing."""
    source = FakeJira({"/rest/api/3/project/search": {"total": 3}})
    out = await source.check_access()
    assert out["ok"] is True
    assert source.requested == ["/rest/api/3/project/search"]


@pytest.mark.asyncio
async def test_authenticated_but_seeing_nothing_is_not_a_credential_failure():
    """Two states, reported separately. The difference between a five-minute
    permissions fix and an afternoon spent on the token."""
    source = FakeJira({"/rest/api/3/project/search": {"total": 0}})
    out = await source.check_access()
    assert out["ok"] is False
    assert "credentials themselves are working" in out["detail"]


@pytest.mark.asyncio
async def test_a_withdrawn_endpoint_says_the_adapter_needs_updating():
    """/rest/api/3/search returns 410 on current Jira Cloud. A fixture
    cannot tell you an endpoint has been removed — only calling it can."""
    import httpx

    real = httpx.AsyncClient

    def handler(request):
        return httpx.Response(410, json={"errorMessages": ["The requested API has been removed."]})

    import app.adapters.requirements_source.jira as mod

    class Gone(JiraRequirementsSource):
        pass

    source = Gone("https://acme.atlassian.net", "a@b.c", "t")
    orig = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)})
    try:
        with pytest.raises(RuntimeError) as raised:
            await source._get("/rest/api/3/search")
        assert "withdrawn" in str(raised.value)
    finally:
        mod.httpx.AsyncClient = orig
