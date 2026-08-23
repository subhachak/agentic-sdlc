"""Config-driven adapter factory. Every concrete adapter class is imported
lazily, inside its own factory branch — not at module top level — so simply
importing this module (or the routers that never call it) never pulls in
`anthropic` unless the claude branch actually runs.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.ports.audit_sink import AuditSink
from app.ports.entity_resolver import EntityResolver
from app.ports.build_deploy import BuildDeploy
from app.ports.code_design_context import CodeDesignContext
from app.ports.llm_provider import LLMProvider
from app.ports.requirements_source import RequirementsSource
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
    from app.adapters.work_dispatch.local_stub import LocalStubWorkDispatch

    return LocalStubWorkDispatch(duration_seconds=settings.local_dispatch_duration_seconds)


def build_entity_resolver(settings: Settings) -> EntityResolver:
    # Only one implementation today. The branch exists so adding a Jira or
    # GitHub resolver is a new arm here, not a change to any caller.
    from app.adapters.entity_resolver.local import LocalEntityResolver

    return LocalEntityResolver()


def build_adapters(settings: Settings) -> Adapters:
    from app.adapters.audit_sink.sqlite_audit_sink import SqliteAuditSink
    from app.adapters.build_deploy.noop import NoOpBuildDeploy
    from app.adapters.code_design_context.stub_similarity import StubSimilarityCodeDesignContext
    from app.adapters.requirements_source.plain_text_csv import PlainTextCSVRequirementsSource
    from app.adapters.test_management.json_file import JsonFileTestManagement

    return Adapters(
        work_dispatch=build_work_dispatch(settings),
        entity_resolver=build_entity_resolver(settings),
        requirements_source=PlainTextCSVRequirementsSource(),
        code_design_context=StubSimilarityCodeDesignContext(),
        test_management=JsonFileTestManagement(),
        build_deploy=NoOpBuildDeploy(),
        llm_provider=build_llm_provider(settings),
        audit_sink=SqliteAuditSink(),
    )
