"""What is separately testable in a repository, and when to ask.

The export scope used to be a text box defaulting to the sample app's name,
so pointing the platform at any real repository produced "nothing to export
for scope 'demo-app' — index the repository first" while the index was
perfectly good. The message named the wrong step, and the right value was
knowable from what had just been indexed.
"""

from app.core import scoping


def test_a_single_unit_repository_needs_no_question():
    paths = {"src/a.ts", "src/b.ts"}
    assert scoping.best(paths, units=["src"]) == "src"


def test_a_monorepo_asks_rather_than_guesses():
    """Two deployable units is a real choice, and guessing it wrong scopes a
    QA run against an app nobody changed."""
    paths = {"apps/web/a.ts", "apps/api/b.py"}
    assert scoping.best(paths, units=["apps/web", "apps/api"]) is None


def test_a_repository_with_no_manifest_is_offered_whole():
    """Real case — a docs or config repository — and not a failure."""
    paths = {"docs/a.md", "docs/b.md"}
    assert scoping.best(paths, units=[]) == ""


def test_a_configured_scope_that_still_matches_is_kept():
    """Changing something else must not silently retarget an export someone
    set deliberately."""
    paths = {"apps/web/a.ts", "apps/api/b.py"}
    units = ["apps/web", "apps/api"]
    assert scoping.best(paths, "apps/api", units) == "apps/api"


def test_a_configured_scope_that_matches_nothing_is_not_used():
    """The bug this exists for: the scope named a subtree that was not in the
    repository, and the export failed blaming the index."""
    paths = {"apps/web/a.ts", "apps/api/b.py"}
    units = ["apps/web", "apps/api"]
    described = scoping.describe(paths, "demo-app", units)
    assert described["configured_matches"] is False
    assert described["must_choose"] is True
    assert {c["path"] for c in described["candidates"]} == {"apps/web", "apps/api", ""}


def test_candidates_are_ordered_by_size_with_the_whole_repository_last():
    paths = {f"big/{i}.ts" for i in range(10)} | {"small/a.ts"}
    found = scoping.candidates(paths, ["big", "small"])
    assert [c["path"] for c in (c.as_dict() for c in found)] == ["big", "small", ""]


def test_nested_units_are_reported_against_their_parent():
    """A package inside an app is a real layout, and someone choosing the
    parent should be able to see what it contains."""
    paths = {"apps/api/a.py", "apps/api/pkg/b.py"}
    found = {c.path: c for c in scoping.candidates(paths, ["apps/api", "apps/api/pkg"])}
    assert found["apps/api"].nested == ["apps/api/pkg"]


def test_markers_are_manifests_not_incidental_files():
    assert scoping.is_marker("package.json")
    assert scoping.is_marker("pyproject.toml")
    assert scoping.is_marker("Api.csproj")
    # A Dockerfile or a CI config can sit anywhere and marks nothing.
    assert not scoping.is_marker("Dockerfile")
    assert not scoping.is_marker("README.md")
