"""Index a GitHub repository by reading its source archive.

One request for the whole tree rather than one per file: the tarball
endpoint returns everything, which keeps a large repository to a single call
and well inside unauthenticated rate limits.

Nothing here executes repository content — the archive is read in memory and
only text files matching known source extensions are parsed. Size and count
caps stop a hostile or simply enormous repository exhausting the process.
"""

from __future__ import annotations

import asyncio
import io
import re
import tarfile
from datetime import datetime, timezone

import httpx

from app.adapters.code_intelligence.parsing import (
    INDEXER_VERSION,
    build_index,
    file_metadata,
    is_ignored,
    is_source,
    load_alias_sets,
)
from app.adapters.code_intelligence.contracts import contract_edges
from app.ports.code_intelligence import (
    CodeDependency,
    CodeFile,
    CodeIndex,
    CodeModule,
    ContractCall,
    FileImport,
    IndexProvenance,
)

_API = "https://api.github.com"
_CODELOAD = "https://codeload.github.com"
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_FILE_BYTES = 400_000
MAX_FILES = 4000

# GitHub builds archives on demand and can return a gateway error while doing
# so. Retrying helps, but api.github.com/tarball can stay unavailable for a
# repository whose archive codeload serves immediately — so try both.
RETRY_STATUSES = (502, 503, 504)
MAX_ATTEMPTS = 3


class GitHubCodeIntelligence:
    def __init__(self, token: str | None = None, max_depth: int = 4) -> None:
        self._token = token
        self._max_depth = max_depth

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def index(self, repo: str, ref: str = "main") -> CodeIndex:
        archive = await self._fetch_archive(repo, ref)
        sources, skipped, tsconfigs, commit_sha = _read_archive(archive)
        if commit_sha is None:
            commit_sha = await self._resolve_sha(repo, ref)
        return _index_from_sources(
            repo, ref, sources, skipped, tsconfigs, self._max_depth, commit_sha
        )

    async def _resolve_sha(self, repo: str, ref: str) -> str | None:
        """Ask which commit a ref points at.

        Only reached when the archive's wrapper directory did not carry it —
        codeload names its wrapper after the ref, not the sha. Failure is not
        fatal: the index records an unpinned provenance and the seeder reports
        it rather than pretending to a commit it does not know.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(
                    f"{_API}/repos/{repo}/commits/{ref}", headers=self._headers
                )
            return resp.json().get("sha") if resp.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    def _archive_urls(self, repo: str, ref: str) -> list[str]:
        """Where to look for the archive, in order of reliability.

        codeload is the CDN that actually serves archives and answers when the
        API's tarball redirect does not. The API endpoint stays as a fallback
        because it handles private-repository auth most predictably.
        """
        return [
            f"{_CODELOAD}/{repo}/tar.gz/refs/heads/{ref}",
            f"{_CODELOAD}/{repo}/tar.gz/{ref}",
            f"{_API}/repos/{repo}/tarball/{ref}",
        ]

    async def _fetch_archive(self, repo: str, ref: str) -> bytes:
        last_status: int | None = None

        try:
            return await self._try_urls(repo, ref)
        except httpx.HTTPError as exc:
            # Wrapped here rather than left to propagate: transport is this
            # adapter's concern, and a caller that had to catch httpx would be
            # coupled to the fact that this one speaks HTTP at all.
            raise ValueError(f"could not reach GitHub for {repo}@{ref}: {exc}") from exc

    async def _try_urls(self, repo: str, ref: str) -> bytes:
        last_status: int | None = None

        async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
            for url in self._archive_urls(repo, ref):
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    resp = await client.get(url, headers=self._headers)
                    last_status = resp.status_code

                    if resp.status_code == 200:
                        if len(resp.content) > MAX_ARCHIVE_BYTES:
                            raise ValueError(
                                f"{repo} archive exceeds "
                                f"{MAX_ARCHIVE_BYTES // 1024 // 1024}MB"
                            )
                        return resp.content

                    if resp.status_code == 403 and "rate limit" in resp.text.lower():
                        raise ValueError(
                            "GitHub rate limit reached. Set GITHUB_TOKEN to raise it."
                        )
                    if resp.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    break  # try the next URL

        if last_status == 404:
            raise ValueError(
                f"{repo}@{ref} not found. Check the ref, and note that private "
                f"repositories need GITHUB_TOKEN set."
            )
        raise ValueError(
            f"could not fetch an archive for {repo}@{ref} (last status {last_status})"
        )


_WRAPPER_SHA = re.compile(r"-([0-9a-f]{40})$")


def _read_archive(
    blob: bytes,
) -> tuple[dict[str, str], int, dict[str, str], str | None]:
    """Pull source text out of a tarball, stripping GitHub's wrapper directory.

    Also returns the commit the archive was cut from, when the wrapper name
    carries it. An index that cannot name its commit cannot be compared with
    the next one, so this is worth reading rather than a second API call.
    """
    sources: dict[str, str] = {}
    skipped = 0
    tsconfigs: dict[str, str] = {}
    commit_sha: str | None = None

    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            # GitHub wraps everything in `owner-repo-sha/`.
            if commit_sha is None and "/" in member.name:
                found = _WRAPPER_SHA.search(member.name.split("/", 1)[0])
                commit_sha = found.group(1) if found else None
            path = member.name.split("/", 1)[1] if "/" in member.name else member.name
            if not path or is_ignored(path):
                continue

            # Every config, not the first: a monorepo has one per package and
            # each maps its aliases to its own source root.
            if path.endswith(("tsconfig.json", "jsconfig.json")):
                handle = archive.extractfile(member)
                if handle:
                    tsconfigs[path] = handle.read().decode("utf-8", "replace")
                continue

            if not is_source(path):
                continue
            if member.size > MAX_FILE_BYTES or len(sources) >= MAX_FILES:
                skipped += 1
                continue

            handle = archive.extractfile(member)
            if handle is None:
                continue
            sources[path] = handle.read().decode("utf-8", "replace")

    return sources, skipped, tsconfigs, commit_sha


def _index_from_sources(
    repo: str,
    ref: str,
    sources: dict[str, str],
    skipped: int,
    tsconfigs: dict[str, str],
    max_depth: int,
    commit_sha: str | None = None,
) -> CodeIndex:
    modules, pairs, imports, stats = build_index(
        sources, alias_sets=load_alias_sets(tsconfigs), max_depth=max_depth
    )

    contracts, unmatched, uncalled = contract_edges(sources)
    stats.contract_edges = len(contracts)
    stats.unmatched_calls = len(unmatched)
    stats.uncalled_routes = len(uncalled)

    by_component: dict[str, list[str]] = {}
    for path, module in modules.items():
        by_component.setdefault(module, []).append(path)

    weights: dict[tuple[str, str], int] = {}
    for pair in pairs:
        weights[pair] = weights.get(pair, 0) + 1

    return CodeIndex(
        repo=repo,
        ref=ref,
        modules=[
            CodeModule(id=cid, paths=sorted(paths))
            for cid, paths in sorted(by_component.items())
        ],
        files=[
            CodeFile(path=p, module=c, **file_metadata(p, sources[p]))
            for p, c in sorted(modules.items())
        ],
        dependencies=[
            CodeDependency(source=s, target=t, weight=w)
            for (s, t), w in sorted(weights.items())
        ],
        imports=[
            FileImport(source=i.source, target=i.target, kind=i.kind, from_test=i.from_test)
            for i in sorted(set(imports), key=lambda i: (i.source, i.target, i.kind))
        ],
        contracts=[
            ContractCall(source=c.source, target=c.target, route=c.route, method=c.method)
            for c in contracts
        ],
        provenance=IndexProvenance(
            commit_sha=commit_sha,
            indexer_version=INDEXER_VERSION,
            indexed_at=datetime.now(timezone.utc).isoformat(),
            files_indexed=len(sources),
            skipped_files=skipped,
            **stats.as_dict(),
        ),
    )
