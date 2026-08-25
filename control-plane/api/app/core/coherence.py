"""Configurations that build fine and cannot work.

`check` answers "can these adapters be constructed" — a GitHub target with
no token, a coding agent with no repository. It is the wrong question for a
whole class of setup mistake, because the adapters construct perfectly and
then read the wrong thing.

The one that prompted this: the graph was indexed from a GitHub repository
while source control was a local working copy of a *different* repository.
Every adapter built. Retrieval then asked source control for 343 files by
path, got none of them, and reported the index as built — in green — because
"read zero files" and "small repository" look identical from the outside.

These are warnings rather than errors on purpose. Each names a combination
that is usually a mistake and occasionally deliberate, and refusing to start
over something occasionally deliberate is worse than saying so clearly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class Finding:
    """One thing that will not work, and what to do about it."""

    id: str
    problem: str
    consequence: str
    remedies: tuple[str, ...]
    keys: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "problem": self.problem,
            "consequence": self.consequence,
            "remedies": list(self.remedies),
            "keys": list(self.keys),
        }


def _same_repo(a: str | None, b: str | None) -> bool:
    """Whether two repository names denote the same repository.

    A URL and an owner/name pair are the same repository written two ways,
    and treating them as different is its own false alarm.
    """
    return bool(a) and bool(b) and _canonical(a) == _canonical(b)


def _canonical(repo: str) -> str:
    repo = repo.strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
    return repo.removesuffix(".git").lower()


def findings(settings: Settings, working_copy_remote: str | None = None) -> list[Finding]:
    """Everything incoherent about this configuration.

    `working_copy_remote` is what the local checkout actually points at, when
    the caller could find out. Supplied rather than read here because that is
    a git call, and this module is meant to stay a pure function of settings.
    """
    out: list[Finding] = []

    # --- grounding reads whatever source control serves ------------------
    # The design agent is grounded by asking source control for the files the
    # graph names. If those two describe different repositories, it is
    # grounded in nothing and nothing says so.
    indexing_remote = settings.code_intelligence_adapter == "github"
    changing_local = settings.source_control_adapter == "local"
    if indexing_remote and changing_local:
        matches = _same_repo(working_copy_remote, settings.code_index_repo)
        if working_copy_remote and not matches:
            out.append(Finding(
                id="grounding-reads-another-repository",
                problem=(
                    f"the graph is indexed from {settings.code_index_repo!r} but the working "
                    f"copy at {settings.target_working_copy!r} is a checkout of "
                    f"{working_copy_remote!r}"
                ),
                consequence=(
                    "the design agent is grounded in nothing: retrieval asks source control "
                    "for files by path and none of them exist in that checkout"
                ),
                remedies=(
                    "set the change target to github, so files are read from the repository "
                    "that was indexed",
                    f"point the working copy at a checkout of {settings.code_index_repo}",
                    "index the working copy instead, by setting the index source to local",
                ),
                keys=("source_control_adapter", "target_working_copy", "code_index_repo"),
            ))
        elif working_copy_remote is None:
            out.append(Finding(
                id="grounding-reads-an-unverified-checkout",
                problem=(
                    f"the graph is indexed from {settings.code_index_repo or 'a remote repository'!r} "
                    f"while files are read from the working copy at "
                    f"{settings.target_working_copy!r}, which does not name a repository"
                ),
                consequence=(
                    "this works only if that directory is a checkout of the indexed "
                    "repository; if it is not, the design agent is grounded in nothing "
                    "and the run does not fail"
                ),
                remedies=(
                    "set the change target to github",
                    "confirm the working copy is a checkout of the indexed repository",
                ),
                keys=("source_control_adapter", "target_working_copy"),
            ))

    # --- changes proposed somewhere the graph does not describe ----------
    # Containment is checked against the graph. A change opened against a
    # repository the graph does not describe cannot be contained by it.
    if (
        settings.source_control_adapter == "github"
        and settings.target_repo
        and settings.code_index_repo
        and not _same_repo(settings.target_repo, settings.code_index_repo)
    ):
        out.append(Finding(
            id="changes-proposed-outside-the-graph",
            problem=(
                f"changes are proposed against {settings.target_repo!r} but the graph "
                f"describes {settings.code_index_repo!r}"
            ),
            consequence=(
                "containment and impact are checked against a graph of a different "
                "codebase, so the modules a change touches cannot be resolved"
            ),
            remedies=(
                "index the repository changes are proposed against",
                "leave the change target unset, so it follows the indexed repository",
            ),
            keys=("target_repo", "code_index_repo"),
        ))

    # --- QA runs against a repository nothing indexed --------------------
    if (
        settings.work_dispatch_adapter == "github-actions"
        and settings.github_repo
        and settings.code_index_repo
        and not _same_repo(settings.github_repo, settings.code_index_repo)
    ):
        out.append(Finding(
            id="ci-elsewhere",
            problem=(
                f"QA is dispatched to {settings.github_repo!r}, which is not the indexed "
                f"repository {settings.code_index_repo!r}"
            ),
            consequence=(
                "legitimate when the workflow lives in its own repository, and a mistake "
                "when it does not — the exported graph describes the indexed one either way"
            ),
            remedies=(
                "leave the CI repository unset, so it follows the indexed repository",
            ),
            keys=("github_repo", "code_index_repo"),
        ))

    return out


def summary(settings: Settings, working_copy_remote: str | None = None) -> list[dict]:
    return [f.as_dict() for f in findings(settings, working_copy_remote)]
