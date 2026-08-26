"""The port list, extracted from the code so a diagram cannot invent one."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
OPTIONAL = {"RepositoryCatalogue", "RollbackCapable", "AccessCheckable"}

# Example implementations. The only hand-written part, and deliberately so:
# what a client might plug in is not derivable from the codebase.
CHIPS = {
    "RequirementsSource": "Jira · Azure DevOps · Confluence · CSV",
    "EntityResolver": "per-system identifier mapping",
    "CodeIntelligence": "GitHub AST indexer · local checkout · language server",
    "CodeDesignContext": "BM25 repo index · vector store · Confluence",
    "ContextGraphStore": "SQLite · PostgreSQL · Neo4j · hosted graph",
    "LLMProvider": "Claude · client-hosted model · mock",
    "DesignAgent": "in-process agent · client's design agent",
    "ImplementationAgent": "in-process agent · GitHub Copilot cloud agent",
    "QAAgent": "local pipeline · client's QA automation",
    "SourceControl": "GitHub · GitLab · Bitbucket · local working copy",
    "WorkDispatch": "GitHub Actions · Jenkins · Azure Pipelines",
    "TestManagement": "JSON file · Xray · TestRail · qTest",
    "BuildDeploy": "no-op recorder · Jenkins · Argo CD · Octopus",
    "AuditSink": "SQLite · client SIEM · WORM store",
    "TestAuthor": "in-process author · client's test agent",
    "TestDataProvider": "JSON store · database lease · fixture service",
    "TestRunner": "Playwright · Cypress · pytest",
}

# Optional capabilities, drawn as a tab on their owner's edge.
TABS = {
    "CodeIntelligence": "RepositoryCatalogue",
    "ImplementationAgent": "AccessCheckable",
    "BuildDeploy": "RollbackCapable",
}

# Reading order around the polygon: intake, then code, then the agents,
# then delivery, then evidence. Adjacency is the argument — the three agent
# seams sit together so their identical treatment is visible.
ORDER = [
    "RequirementsSource", "EntityResolver", "CodeIntelligence",
    "CodeDesignContext", "ContextGraphStore", "LLMProvider",
    "DesignAgent", "ImplementationAgent", "QAAgent",
    "TestAuthor", "TestDataProvider", "TestRunner",
    "WorkDispatch", "SourceControl", "TestManagement",
    "BuildDeploy", "AuditSink",
]

EXECUTION_PLANE = {"TestAuthor", "TestDataProvider", "TestRunner"}


def discovered() -> dict[str, str]:
    """Every Protocol the codebase declares, and which plane it is in."""
    found: dict[str, str] = {}
    for path in sorted((ROOT / "control-plane/api/app/ports").glob("*.py")):
        for name in re.findall(r"^class (\w+)\(Protocol\)", path.read_text(), re.M):
            found[name] = "control"
    for path in sorted((ROOT / "execution-plane/qa/orchestrator").glob("ports*.py")):
        for name in re.findall(r"^class (\w+)\(Protocol\)", path.read_text(), re.M):
            found[name] = "execution"
    return found


def required() -> list[str]:
    found = discovered()
    ports = [p for p in found if p not in OPTIONAL]

    missing = sorted(set(ports) - set(ORDER))
    extra = sorted(set(ORDER) - set(ports))
    if missing or extra:
        raise SystemExit(
            f"the diagram's port list has drifted from the code.\n"
            f"  declared but not drawn: {missing}\n"
            f"  drawn but not declared: {extra}"
        )
    return ORDER


# ── the grouped view ──────────────────────────────────────────────────────
# Eight families instead of seventeen edges. Legible at slide size, and it
# gives up the claim the full figure makes: that every seam is equal. Both
# exist because that trade is real and worth seeing.
#
# On this figure the chips are the ports themselves — the edge is the
# family, and what sits outside it is what the family actually contains.
FAMILIES = [
    ("Intake", ["RequirementsSource", "EntityResolver"]),
    ("Code context", ["CodeIntelligence", "CodeDesignContext", "ContextGraphStore"]),
    ("Models", ["LLMProvider"]),
    ("Agents", ["DesignAgent", "ImplementationAgent", "QAAgent"]),
    ("Test execution", ["TestAuthor", "TestDataProvider", "TestRunner"]),
    ("Remote work", ["WorkDispatch"]),
    ("Delivery", ["SourceControl", "BuildDeploy", "TestManagement"]),
    ("Evidence", ["AuditSink"]),
]

FAMILY_EXECUTION = {"Test execution"}


def grouped() -> tuple[list[str], dict[str, str]]:
    """Family names, and the ports each one holds.

    Checked against the full list, so a port cannot be silently dropped by
    being left out of a group — which is exactly how a simplified diagram
    starts describing a platform that does not exist.
    """
    covered = [p for _, members in FAMILIES for p in members]
    duplicated = sorted({p for p in covered if covered.count(p) > 1})
    missing = sorted(set(required()) - set(covered))
    stray = sorted(set(covered) - set(required()))
    if duplicated or missing or stray:
        raise SystemExit(
            f"the grouped view does not partition the ports.\n"
            f"  in two groups: {duplicated}\n"
            f"  in no group:   {missing}\n"
            f"  not a port:    {stray}"
        )
    return (
        [name for name, _ in FAMILIES],
        {name: " · ".join(members) for name, members in FAMILIES},
    )
