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


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider_adapter == "claude":
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

        return LocalPathCodeIntelligence(
            Path(settings.code_index_local_root), max_depth=settings.code_index_max_depth
        )

    from app.adapters.code_intelligence.github import GitHubCodeIntelligence

    # Public repositories index without a token; one is used when present, for
    # private repositories and to lift the rate limit.
    return GitHubCodeIntelligence(
        token=settings.github_token, max_depth=settings.code_index_max_depth
    )


def build_source_control(settings: Settings) -> SourceControl:
    if settings.source_control_adapter == "github":
        if not settings.github_token:
            raise ValueError("source_control_adapter=github needs GITHUB_TOKEN")
        from app.adapters.source_control.github import GitHubSourceControl

        return GitHubSourceControl(token=settings.github_token)

    from pathlib import Path as _Path

    from app.adapters.source_control.local_working_copy import LocalWorkingCopy

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


def build_adapters(settings: Settings, graph: Any = None) -> Adapters:
    from app.adapters.audit_sink.sqlite_audit_sink import SqliteAuditSink
    from app.adapters.build_deploy.noop import NoOpBuildDeploy
    from app.adapters.requirements_source.plain_text_csv import PlainTextCSVRequirementsSource
    from app.adapters.test_management.json_file import JsonFileTestManagement

    source_control = build_source_control(settings)

    return Adapters(
        work_dispatch=build_work_dispatch(settings),
        entity_resolver=build_entity_resolver(settings),
        code_intelligence=build_code_intelligence(settings),
        source_control=source_control,
        requirements_source=PlainTextCSVRequirementsSource(),
        code_design_context=build_code_design_context(settings, graph, source_control),
        test_management=JsonFileTestManagement(),
        build_deploy=NoOpBuildDeploy(),
        llm_provider=build_llm_provider(settings),
        audit_sink=SqliteAuditSink(),
    )
