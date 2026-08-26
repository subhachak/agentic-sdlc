"""Config-driven adapter factory. Every concrete adapter class is imported
lazily, inside its own factory branch — not at module top level — so simply
importing this module (or the routers that never call it) never pulls in
`anthropic` unless the claude branch actually runs.
"""

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.ports.audit_sink import AuditSink
from app.ports.entity_resolver import EntityResolver
from app.ports.build_deploy import BuildDeploy
from app.ports.code_design_context import CodeDesignContext
from app.ports.code_intelligence import CodeIntelligence
from app.ports.llm_provider import LLMProvider
from app.ports.requirements_source import RequirementsSource
from app.ports.source_control import SourceControl
from app.ports.test_management import TestManagement
from app.ports.work_dispatch import WorkDispatch


@dataclass
class Adapters:
    """A bag of already-constructed adapter instances — no validation needed,
    so a plain dataclass (not a pydantic BaseModel): Protocol types aren't
    runtime_checkable, and pydantic can't build an isinstance validator for
    them.
    """

    requirements_source: RequirementsSource
    code_design_context: CodeDesignContext
    test_management: TestManagement
    build_deploy: BuildDeploy
    llm_provider: LLMProvider
    audit_sink: AuditSink
    work_dispatch: WorkDispatch
    entity_resolver: EntityResolver
    code_intelligence: CodeIntelligence
    source_control: SourceControl
    # None when the platform writes the change itself.
    implementation_dispatch: WorkDispatch | None
    implementation_agent: Any


def _require_directory(path: str | None, selection: str, setting: str) -> None:
    """A local adapter pointed at nothing cannot work.

    Checked at construction because it is checkable there, and because the
    alternative is discovering it when a run reaches the phase that uses it.
    Existence only — not that it is a git repository, since the local
    adapters degrade sensibly on a plain directory and that is deliberate.
    """
    from pathlib import Path as _Path

    if not path or not _Path(path).is_dir():
        raise ValueError(
            f"{selection} needs {setting} to be a directory that exists; "
            f"{path!r} is not"
        )


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider_adapter == "claude":
        if not settings.anthropic_api_key:
            # The SDK constructs happily without a key and fails at the first
            # call, which is deep inside a run and after the gates have been
            # approved. Refusing here turns that into a configuration error
            # someone can read.
            raise ValueError(
                "llm_provider_adapter=claude needs ANTHROPIC_API_KEY"
            )
        from app.adapters.llm.claude_adapter import ClaudeLLMProvider

        return ClaudeLLMProvider(api_key=settings.anthropic_api_key, model=settings.claude_model)

    from app.adapters.llm.mock_adapter import MockLLMProvider

    return MockLLMProvider()


def build_work_dispatch(settings: Settings) -> WorkDispatch:
    if settings.work_dispatch_adapter == "github-actions":
        if not (settings.github_repo and settings.github_token):
            raise ValueError(
                "work_dispatch_adapter=github-actions needs GITHUB_REPO and GITHUB_TOKEN"
            )
        from app.adapters.work_dispatch.github_actions import GitHubActionsWorkDispatch

        return GitHubActionsWorkDispatch(
            repo=settings.github_repo,
            token=settings.github_token,
            workflow_file=settings.github_workflow_file,
            ref=settings.github_ref,
        )
    if settings.work_dispatch_adapter == "local-pipeline":
        from pathlib import Path as _Path

        from app.adapters.work_dispatch.local_pipeline import LocalPipelineWorkDispatch

        _require_directory(
            settings.target_working_copy,
            "work_dispatch_adapter=local-pipeline",
            "TARGET_WORKING_COPY",
        )
        return LocalPipelineWorkDispatch(
            _Path(settings.target_working_copy),
            base_ref=settings.target_ref,
            secrets={"ANTHROPIC_API_KEY": settings.anthropic_api_key or ""},
        )

    from app.adapters.work_dispatch.local_stub import LocalStubWorkDispatch

    return LocalStubWorkDispatch(duration_seconds=settings.local_dispatch_duration_seconds)


def build_entity_resolver(settings: Settings) -> EntityResolver:
    # Only one implementation today. The branch exists so adding a Jira or
    # GitHub resolver is a new arm here, not a change to any caller.
    from app.adapters.entity_resolver.local import LocalEntityResolver

    return LocalEntityResolver()


def build_code_intelligence(settings: Settings) -> CodeIntelligence:
    if settings.code_intelligence_adapter == "local":
        from pathlib import Path

        from app.adapters.code_intelligence.local_path import LocalPathCodeIntelligence

        _require_directory(
            settings.code_index_local_root,
            "code_intelligence_adapter=local",
            "CODE_INDEX_LOCAL_ROOT",
        )
        return LocalPathCodeIntelligence(
            Path(settings.code_index_local_root), max_depth=settings.code_index_max_depth
        )

    from app.adapters.code_intelligence.github import GitHubCodeIntelligence

    # Public repositories index without a token; one is used when present, for
    # private repositories and to lift the rate limit.
    return GitHubCodeIntelligence(
        token=settings.github_token, max_depth=settings.code_index_max_depth
    )


def build_implementation_dispatch(settings: Settings) -> WorkDispatch | None:
    """Who the implementation phase hands work to, when it is not this
    platform's own agent.

    Separate from `work_dispatch` because the two phases no longer share a
    provider: QA may run in the client's CI while the change is written by
    their coding agent. The reconciler resolves per dispatch row, so both can
    be in flight at once.
    """
    if settings.implementation_agent == "inline":
        return None

    if not (settings.target_repo and settings.github_token):
        raise ValueError(
            "implementation_agent=github-copilot needs TARGET_REPO and GITHUB_TOKEN"
        )
    from app.adapters.work_dispatch.github_copilot import GitHubCopilotWorkDispatch

    return GitHubCopilotWorkDispatch(
        repo=settings.target_repo,
        token=settings.github_token,
        base_ref=settings.target_ref,
        model=settings.copilot_model,
        custom_agent=settings.copilot_custom_agent,
    )


def build_source_control(settings: Settings) -> SourceControl:
    if settings.source_control_adapter == "github":
        if not settings.github_token:
            raise ValueError("source_control_adapter=github needs GITHUB_TOKEN")
        from app.adapters.source_control.github import GitHubSourceControl

        return GitHubSourceControl(token=settings.github_token)

    from pathlib import Path as _Path

    from app.adapters.source_control.local_working_copy import LocalWorkingCopy

    _require_directory(
        settings.target_working_copy,
        "source_control_adapter=local",
        "TARGET_WORKING_COPY",
    )
    return LocalWorkingCopy(_Path(settings.target_working_copy))


def build_code_design_context(
    settings: Settings, graph: Any, source_control: SourceControl
) -> CodeDesignContext:
    """Grounding for the design agent.

    `graph` is typed `Any` rather than `ContextGraphStore` on purpose: that
    Protocol lives beside the SQLAlchemy store, and importing it here would
    pull the database driver into a module whose whole point is that nothing
    is imported until its branch runs.

    Takes the graph as an argument rather than constructing one, because
    retrieval must read the same snapshot that impact and containment read.
    Two indexes of the same repository built at different moments would let
    the agent be shown code the graph does not have.
    """
    if settings.code_design_context_adapter == "repo":
        from app.adapters.code_design_context.repo_index import IndexedRepoCodeDesignContext

        return IndexedRepoCodeDesignContext(
            graph=graph,
            source_control=source_control,
            repo=settings.target_repo or settings.code_index_repo or "",
            ref=settings.target_ref,
        )

    from app.adapters.code_design_context.stub_similarity import StubSimilarityCodeDesignContext

    return StubSimilarityCodeDesignContext()


def build_requirements_source(settings: Settings) -> RequirementsSource:
    """Where work arrives from."""
    if settings.requirements_source_adapter == "jira":
        missing = [
            name
            for name, value in (
                ("JIRA_BASE_URL", settings.jira_base_url),
                ("JIRA_EMAIL", settings.jira_email),
                ("JIRA_API_TOKEN", settings.jira_api_token),
            )
            if not value
        ]
        if missing:
            # Refused at construction, which is what the console's preflight
            # turns into "this needs a token" while someone is choosing,
            # rather than a run failing at the intake phase.
            raise ValueError(
                "requirements_source_adapter=jira needs " + ", ".join(missing)
            )
        from app.adapters.requirements_source.jira import JiraRequirementsSource

        return JiraRequirementsSource(
            base_url=settings.jira_base_url or "",
            email=settings.jira_email or "",
            api_token=settings.jira_api_token or "",
            default_query=settings.jira_query,
        )

    from app.adapters.requirements_source.plain_text_csv import (
        PlainTextCSVRequirementsSource,
    )

    return PlainTextCSVRequirementsSource()


def build_test_management(settings: Settings) -> TestManagement:
    """Where test cases and their results live for the client."""
    from app.adapters.test_management.json_file import JsonFileTestManagement

    return JsonFileTestManagement()


def build_build_deploy(settings: Settings) -> BuildDeploy:
    """How a release reaches an environment."""
    from app.adapters.build_deploy.noop import NoOpBuildDeploy

    return NoOpBuildDeploy()


def build_audit_sink(settings: Settings) -> AuditSink:
    """Where the decision trail is written.

    A client with a retention or WORM requirement replaces this; the trail
    is the thing an auditor asks for, so where it lands is theirs to choose.
    """
    from app.adapters.audit_sink.sqlite_audit_sink import SqliteAuditSink

    return SqliteAuditSink()


def build_implementation_agent(settings: Settings) -> Any:
    """Who writes the change.

    A typed façade over the dispatch seam rather than a second one: the
    dispatched arm hands its inputs back to the phase, which owns the row.
    `inline` writes in-process and is reviewed before anything is written
    anywhere.
    """
    if settings.implementation_agent == "inline":
        from app.adapters.implementation_agent.inline import InlineImplementationAgent
        from app.agents.implementation import SYSTEM as IMPLEMENTATION_SYSTEM
        from app.agents.implementation import Implementation, build_prompt

        return InlineImplementationAgent(
            llm_provider=build_llm_provider(settings),
            system_prompt=IMPLEMENTATION_SYSTEM,
            schema=Implementation,
            build_prompt=build_prompt,
        )

    from app.adapters.implementation_agent.dispatched import (
        DispatchedImplementationAgent,
    )

    return DispatchedImplementationAgent(
        provider=settings.implementation_agent,
        dispatch=build_implementation_dispatch(settings),
    )


def build_design_agent(settings: Settings) -> Any:
    """Who proposes the design.

    `inline` is this platform's own agent. A client agent is dispatched and
    read back later, which is why this returns through a port rather than
    being called directly.
    """
    from app.adapters.design_agent.inline import InlineDesignAgent

    return InlineDesignAgent()


def build_context_graph_store(settings: Settings) -> Any:
    """Where the context graph is persisted.

    The platform's central abstraction, and the only port that used to be
    constructed directly in main.py — so a client wanting Postgres, Neo4j or
    a hosted graph service had to edit the entry point.

    The storage engine is not the architecture. The versioned semantic model
    is, and it is the Protocol in app/ports/context_graph.py; SQLite is one
    implementation of it.
    """
    from app.core.context_graph import SqlContextGraph

    return SqlContextGraph(build_entity_resolver(settings))


def build_adapters(settings: Settings, graph: Any = None) -> Adapters:
    source_control = build_source_control(settings)

    return Adapters(
        work_dispatch=build_work_dispatch(settings),
        entity_resolver=build_entity_resolver(settings),
        code_intelligence=build_code_intelligence(settings),
        source_control=source_control,
        implementation_dispatch=build_implementation_dispatch(settings),
        implementation_agent=build_implementation_agent(settings),
        requirements_source=build_requirements_source(settings),
        code_design_context=build_code_design_context(settings, graph, source_control),
        test_management=build_test_management(settings),
        build_deploy=build_build_deploy(settings),
        llm_provider=build_llm_provider(settings),
        audit_sink=build_audit_sink(settings),
    )
