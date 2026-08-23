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
import tarfile

import httpx

from app.adapters.code_intelligence.parsing import (
    build_index,
    is_ignored,
    is_source,
    load_aliases,
)
from app.ports.code_intelligence import (
    CodeComponent,
    CodeDependency,
    CodeFile,
    CodeIndex,
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
        sources, skipped, tsconfig = _read_archive(archive)
        return _index_from_sources(repo, ref, sources, skipped, tsconfig, self._max_depth)

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


def _read_archive(blob: bytes) -> tuple[dict[str, str], int, str | None]:
    """Pull source text out of a tarball, stripping GitHub's wrapper directory."""
    sources: dict[str, str] = {}
    skipped = 0
    tsconfig: str | None = None

    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            # GitHub wraps everything in `owner-repo-sha/`.
            path = member.name.split("/", 1)[1] if "/" in member.name else member.name
            if not path or is_ignored(path):
                continue

            if path.endswith("tsconfig.json") and tsconfig is None:
                handle = archive.extractfile(member)
                if handle:
                    tsconfig = handle.read().decode("utf-8", "replace")
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

    return sources, skipped, tsconfig


def _index_from_sources(
    repo: str,
    ref: str,
    sources: dict[str, str],
    skipped: int,
    tsconfig: str | None,
    max_depth: int,
) -> CodeIndex:
    aliases = load_aliases(tsconfig)
    components, pairs, unresolved = build_index(
        sources, aliases=aliases, alias_root="", max_depth=max_depth
    )

    by_component: dict[str, list[str]] = {}
    for path, component in components.items():
        by_component.setdefault(component, []).append(path)

    weights: dict[tuple[str, str], int] = {}
    for pair in pairs:
        weights[pair] = weights.get(pair, 0) + 1

    return CodeIndex(
        repo=repo,
        ref=ref,
        components=[
            CodeComponent(id=cid, paths=sorted(paths))
            for cid, paths in sorted(by_component.items())
        ],
        files=[CodeFile(path=p, component=c) for p, c in sorted(components.items())],
        dependencies=[
            CodeDependency(source=s, target=t, weight=w)
            for (s, t), w in sorted(weights.items())
        ],
        unresolved_imports=unresolved,
        skipped_files=skipped,
    )
