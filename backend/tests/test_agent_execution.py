from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langchain_core.tools import ToolException
from pydantic import ValidationError

import agents.execution.agent as execution_agent_module
import agents.execution.executor as execution_executor_module
from agents.execution.agent import (
    Agent,
    FindingBatch,
    RemediationFindingOutput,
    ReviewTarget,
)
from agents.execution.executor import ReviewExecutionService, _source_failure_code
from agents.execution.orchestrator import OrchestratorAgent
from agents.execution.redaction import redact_text
from agents.execution.tools import (
    REPOSITORY_REVIEW_TOOLS,
    ToolExecutionContext,
    list_paths,
    search_code,
)
from auth.errors import (
    GithubAuthorizationRequired,
    ProviderRateLimited,
    ProviderUnavailable,
    RepositoryNotFound,
)
from db.types import RepositorySource, ReviewCategory
from external_repositories.service import ReviewSourceFileError
from findings.models import Finding
from notifications.models import NotificationEventType
from remediations.models import (
    Remediation,
    RemediationPullRequestOutboxJob,
    RemediationStatus,
)
from reviews.config import AgentExecutionSettings
from reviews.dispatch import _open_connection


def _tool_context() -> ToolExecutionContext:
    return ToolExecutionContext(
        owner_id=None,  # type: ignore[arg-type]
        source_kind="github",
        source_identifier="42",
        source_revision="a" * 40,
        repository_access=None,  # type: ignore[arg-type]
        review_id=UUID("00000000-0000-0000-0000-000000000001"),
    )


def _remediation_finding(**overrides: str) -> RemediationFindingOutput:
    values = {
        "severity": "high",
        "title": "Missing authorization check",
        "explanation": "The route does not verify the caller's organization.",
        "prompt_text": "Add an organization authorization check to the route.",
        "diff": (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1 @@\n"
            "-allow = True\n"
            "+allow = has_organization_access(user)\n"
        ),
    }
    values.update(overrides)
    return RemediationFindingOutput.model_validate(values)


def test_agent_has_repository_tools_by_default() -> None:
    agent = Agent(
        provider="openai",
        model="gpt-6.1-sol",
        skills=(),
        metadata={"category": "security", "personality": "Careful."},
    )

    assert agent.tools == REPOSITORY_REVIEW_TOOLS
    assert [tool.name for tool in agent.tools] == [
        "list_paths",
        "read_file",
        "search_code",
    ]


def test_repository_tools_require_source_without_exposing_runtime_context() -> None:
    schemas = {
        tool.name: tool.tool_call_schema.model_json_schema()["properties"]
        for tool in REPOSITORY_REVIEW_TOOLS
    }

    assert set(schemas["list_paths"]) == {"source", "path_prefix", "max_results"}
    assert set(schemas["read_file"]) == {"source", "path"}
    assert set(schemas["search_code"]) == {"source", "query", "path_prefix"}
    assert (
        "must match the target source" in schemas["list_paths"]["source"]["description"]
    )
    assert (
        "Use null for the repository root"
        in schemas["list_paths"]["path_prefix"]["description"]
    )
    assert (
        "Do not use '.', './', '..'"
        in schemas["search_code"]["path_prefix"]["description"]
    )
    assert "returned by list_paths" in schemas["read_file"]["path"]["description"]
    assert "Literal text" in schemas["search_code"]["query"]["description"]


def test_list_paths_logs_arguments_and_a_result_summary(caplog) -> None:
    class RepositoryAccess:
        def list_paths(self, **kwargs):
            assert kwargs["path_prefix"] == "backend"
            assert kwargs["log_context"].review_id
            return ["backend/main.py", "backend/worker.py"], False

    runtime = SimpleNamespace(
        context=ToolExecutionContext(
            owner_id=uuid4(),
            source_kind="github",
            source_identifier="123",
            source_revision="a" * 40,
            repository_access=RepositoryAccess(),  # type: ignore[arg-type]
            review_id=uuid4(),
        )
    )

    with caplog.at_level("INFO", logger="trace.agent_execution.tools"):
        result = list_paths.func(  # type: ignore[union-attr]
            source="github",
            path_prefix="backend",
            max_results=25,
            runtime=runtime,
        )

    assert result == {
        "paths": ["backend/main.py", "backend/worker.py"],
        "truncated": False,
    }
    assert '"event": "repository_tool_started"' in caplog.text
    assert '"path_prefix": "backend"' in caplog.text
    assert '"path_count": 2' in caplog.text


def test_search_code_skips_unsearchable_files() -> None:
    class RepositoryAccess:
        def list_paths(self, **_kwargs):
            return ["assets/logo.png", "src/app.py"], False

        def read_file(self, *, path, **_kwargs):
            if path == "assets/logo.png":
                raise ReviewSourceFileError("file_not_utf8")
            return "launch_enabled = true\n"

    runtime = SimpleNamespace(
        context=ToolExecutionContext(
            owner_id=uuid4(),
            source_kind="github",
            source_identifier="123",
            source_revision="a" * 40,
            repository_access=RepositoryAccess(),  # type: ignore[arg-type]
            review_id=uuid4(),
        )
    )

    result = search_code.func(  # type: ignore[union-attr]
        source="github",
        query="launch_enabled",
        runtime=runtime,
    )

    assert result == {
        "matches": [
            {
                "path": "src/app.py",
                "line_number": 1,
                "line": "launch_enabled = true",
            }
        ],
        "truncated": False,
        "files_truncated": False,
        "skipped_files": 1,
    }


def test_repository_tools_return_expected_tool_errors_to_the_model() -> None:
    runtime = SimpleNamespace(context=_tool_context())

    assert all(tool.handle_tool_error is True for tool in REPOSITORY_REVIEW_TOOLS)
    with pytest.raises(ToolException, match="source_mismatch"):
        list_paths.func(  # type: ignore[union-attr]
            source="local",
            path_prefix=None,
            max_results=1,
            runtime=runtime,
        )


def test_agent_prompt_identifies_the_tool_inspected_review_target(monkeypatch) -> None:
    messages = []
    create_agent_arguments = {}

    class LangChainAgent:
        def invoke(self, inputs, *, context):
            messages.extend(inputs["messages"])
            assert context == _tool_context()
            return {"structured_response": FindingBatch()}

    def fake_create_agent(**kwargs):
        create_agent_arguments.update(kwargs)
        return LangChainAgent()

    model = object()
    monkeypatch.setattr(Agent, "_model", lambda _agent: model)
    monkeypatch.setattr(execution_agent_module, "create_agent", fake_create_agent)

    Agent(provider="openai", model="test-model").run(
        review_target=ReviewTarget(
            source_kind="gitlab",
            source_identifier="group/project",
            source_revision="b" * 40,
        ),
        tool_context=_tool_context(),
    )

    assert create_agent_arguments["model"] is model
    assert create_agent_arguments["tools"] == list(REPOSITORY_REVIEW_TOOLS)
    assert create_agent_arguments["response_format"] is FindingBatch
    assert "repository tools" in create_agent_arguments["system_prompt"]
    assert "prompt_text" in create_agent_arguments["system_prompt"]
    assert "diff --git" in create_agent_arguments["system_prompt"]
    assert "files you inspected" in create_agent_arguments["system_prompt"]
    assert create_agent_arguments["context_schema"] is ToolExecutionContext
    assert messages[0].content == (
        "Review target:\n"
        "- source kind: gitlab\n"
        "- source identifier: group/project\n"
        f"- immutable revision: {'b' * 40}\n\n"
        "Inspect this target with your repository tools before returning findings."
    )


def test_orchestrator_runs_only_supplied_agents(monkeypatch) -> None:
    invoked: list[str] = []

    def fake_run(
        self, *, review_target: ReviewTarget, tool_context: ToolExecutionContext
    ) -> FindingBatch:
        invoked.append(self.model)
        assert review_target.source_identifier == "workspace-123"
        assert tool_context == _tool_context()
        return FindingBatch(
            findings=[
                _remediation_finding(
                    severity="low",
                    title="Example",
                    explanation="Example explanation",
                )
            ]
        )

    monkeypatch.setattr(Agent, "run", fake_run)
    result = OrchestratorAgent().run(
        review_target=ReviewTarget(
            source_kind="github",
            source_identifier="workspace-123",
            source_revision="a" * 40,
        ),
        tool_context=_tool_context(),
        agents=(
            Agent(provider="openai", model="first"),
            Agent(provider="openai", model="second"),
        ),
    )

    assert invoked == ["first", "second"]
    assert len(result) == 2


def test_redaction_removes_common_provider_keys() -> None:
    value = redact_text("token sk-example_secret_key_123456789012345")

    assert "sk-example_secret_key_123456789012345" not in value
    assert "[REDACTED_SECRET]" in value


@pytest.mark.parametrize("field", ["prompt_text", "diff"])
def test_remediation_finding_output_requires_fix_content(field: str) -> None:
    values = _remediation_finding().model_dump()
    values[field] = ""

    with pytest.raises(ValidationError):
        RemediationFindingOutput.model_validate(values)


@pytest.mark.parametrize(
    ("finding_inserted", "expected_notification_count"),
    [(True, 1), (False, 0)],
)
def test_new_findings_create_matching_remediations_and_deduplicated_findings_do_not(
    monkeypatch, finding_inserted, expected_notification_count
) -> None:
    service = object.__new__(ReviewExecutionService)
    owner_id = uuid4()
    review_id = uuid4()
    project_id = uuid4()
    finding_id = uuid4()
    remediation_id = uuid4()
    notifications: list[dict[str, object]] = []
    remediation_statements = []

    generated_ids = iter((finding_id, remediation_id))
    monkeypatch.setattr(
        execution_executor_module,
        "uuid7",
        lambda: next(generated_ids),
    )

    class InsertResult:
        def scalars(self):
            return self

        def all(self):
            return [finding_id] if finding_inserted else []

    class PreferenceResult:
        def scalar_one_or_none(self):
            return False

    class ProjectResult:
        def mappings(self):
            return self

        def one_or_none(self):
            return None

    class Connection:
        select_count = 0

        def execute(self, statement):
            if not hasattr(statement, "table"):
                self.select_count += 1
                return PreferenceResult() if self.select_count == 1 else ProjectResult()
            if statement.table.name == Remediation.__tablename__:
                remediation_statements.append(statement)
                return None
            return InsertResult()

    @contextmanager
    def fake_principal_transaction(_engine, _owner_id):
        yield Connection()

    def fake_create_notification(_connection, **kwargs):
        notifications.append(kwargs)

    monkeypatch.setattr(
        execution_executor_module,
        "principal_transaction",
        fake_principal_transaction,
    )
    monkeypatch.setattr(
        execution_executor_module,
        "create_notification",
        fake_create_notification,
    )

    service._engine = object()
    service._persist_findings(
        owner_id=owner_id,
        review=SimpleNamespace(id=review_id, project_id=project_id),
        review_agent=SimpleNamespace(
            id=uuid4(),
            agent_id=uuid4(),
            agent_specialization=ReviewCategory.SECURITY,
        ),
        finding_outputs=[
            _remediation_finding(
                prompt_text="Use token sk-example_secret_key_123456789012345 safely."
            )
        ],
    )

    assert len(notifications) == expected_notification_count
    if notifications:
        assert notifications == [
            {
                "owner_id": owner_id,
                "event_type": NotificationEventType.FINDINGS_AVAILABLE,
                "dedupe_key": f"review:{review_id}:findings_available",
                "review_id": review_id,
            }
        ]
    if finding_inserted:
        assert len(remediation_statements) == 1
        remediation_values = remediation_statements[0].compile().params
        assert project_id in remediation_values.values()
        assert finding_id in remediation_values.values()
        assert remediation_id in remediation_values.values()
        assert RemediationStatus.PROPOSED in remediation_values.values()
        assert "sk-example_secret_key_123456789012345" not in str(remediation_values)
        assert "[REDACTED_SECRET]" in str(remediation_values)
    else:
        assert remediation_statements == []


def test_eligible_new_remediations_create_an_automatic_pr_outbox_record(
    monkeypatch,
) -> None:
    service = object.__new__(ReviewExecutionService)
    owner_id, review_id, project_id, finding_id, remediation_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    statements = []
    generated_ids = iter((finding_id, remediation_id))
    monkeypatch.setattr(execution_executor_module, "uuid7", lambda: next(generated_ids))

    class InsertResult:
        def scalars(self):
            return self

        def all(self):
            return [finding_id]

    class PreferenceResult:
        def scalar_one_or_none(self):
            return True

    class ProjectResult:
        def mappings(self):
            return self

        def one_or_none(self):
            return {
                "source": RepositorySource.GITHUB,
                "external_repository_id": "123",
                "branch_name": "main",
            }

    class Connection:
        select_count = 0

        def execute(self, statement):
            statements.append(statement)
            if not hasattr(statement, "table"):
                self.select_count += 1
                return PreferenceResult() if self.select_count == 1 else ProjectResult()
            if statement.table.name == Finding.__tablename__:
                return InsertResult()
            return None

    @contextmanager
    def fake_principal_transaction(_engine, _owner_id):
        yield Connection()

    monkeypatch.setattr(
        execution_executor_module,
        "principal_transaction",
        fake_principal_transaction,
    )
    monkeypatch.setattr(
        execution_executor_module, "create_notification", lambda *_a, **_k: None
    )
    service._engine = object()
    service._persist_findings(
        owner_id=owner_id,
        review=SimpleNamespace(id=review_id, project_id=project_id),
        review_agent=SimpleNamespace(
            id=uuid4(), agent_id=uuid4(), agent_specialization=ReviewCategory.SECURITY
        ),
        finding_outputs=[_remediation_finding()],
    )

    assert any(
        RemediationPullRequestOutboxJob.__tablename__ in str(statement)
        for statement in statements
    )


@pytest.mark.parametrize(
    ("error", "failure_code"),
    [
        (GithubAuthorizationRequired(), "source_authorization_failed"),
        (ProviderRateLimited(), "source_rate_limited"),
        (ProviderUnavailable(), "source_unavailable"),
        (RepositoryNotFound(), "source_not_found"),
    ],
)
def test_repository_tool_failures_have_source_specific_codes(
    error, failure_code
) -> None:
    assert _source_failure_code(error) == failure_code


def test_local_review_does_not_open_github_source_access() -> None:
    service = object.__new__(ReviewExecutionService)
    service._repository_service = SimpleNamespace(
        open_review_github_source_access=lambda **_kwargs: pytest.fail(
            "GitHub source access must not open for a local review"
        )
    )
    service._settings = SimpleNamespace(
        github_max_concurrent_requests=2,
        github_get_max_attempts=3,
        github_retry_base_seconds=0.25,
        github_retry_max_seconds=2.0,
    )
    review = SimpleNamespace(
        source_kind=SimpleNamespace(value="local"),
        source_identifier="workspace-123",
        source_revision="revision-123",
    )

    with service._open_review_source_access(  # type: ignore[arg-type]
        owner_id=uuid4(),
        review=review,
    ) as repository_access:
        assert repository_access is None


def test_github_tool_requires_github_source_access() -> None:
    context = ToolExecutionContext(
        owner_id=uuid4(),
        source_kind="github",
        source_identifier="123",
        source_revision="a" * 40,
        repository_access=None,
        review_id=uuid4(),
    )

    with pytest.raises(ToolException, match="source_execution_unsupported"):
        context.github_repository_access()


def test_execution_settings_allow_disabled_langsmith(monkeypatch) -> None:
    monkeypatch.setenv("REVIEW_RABBITMQ_URL", "amqp://guest:guest@localhost/")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    settings = AgentExecutionSettings()

    settings.validate_for_execution()

    def unexpected_client(**_kwargs):
        raise AssertionError("LangSmith client must not be created")

    monkeypatch.setattr(execution_executor_module, "Client", unexpected_client)
    service = ReviewExecutionService(
        engine=None,  # type: ignore[arg-type]
        credential_service=None,  # type: ignore[arg-type]
        repository_service=None,  # type: ignore[arg-type]
        settings=settings,
    )

    assert service._langsmith is None


def test_execution_settings_require_key_when_langsmith_enabled(monkeypatch) -> None:
    monkeypatch.setenv("REVIEW_RABBITMQ_URL", "amqp://guest:guest@localhost/")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LangSmith API key is required"):
        AgentExecutionSettings().validate_for_execution()

    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    AgentExecutionSettings().validate_for_execution()


def test_review_broker_connection_can_disable_heartbeat_for_long_agent_runs(
    monkeypatch,
) -> None:
    captured_heartbeats: list[int] = []

    def fake_connection(parameters):
        captured_heartbeats.append(parameters.heartbeat)
        return object()

    monkeypatch.setattr("reviews.dispatch.pika.BlockingConnection", fake_connection)

    _open_connection("amqp://guest:guest@localhost/")
    _open_connection("amqp://guest:guest@localhost/", heartbeat=0)

    assert captured_heartbeats == [30, 0]


def test_execution_service_hides_langsmith_inputs_and_outputs(monkeypatch) -> None:
    monkeypatch.setenv("REVIEW_RABBITMQ_URL", "amqp://guest:guest@localhost/")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    client_arguments = {}

    def fake_client(**kwargs):
        client_arguments.update(kwargs)
        return object()

    monkeypatch.setattr(execution_executor_module, "Client", fake_client)

    ReviewExecutionService(
        engine=None,  # type: ignore[arg-type]
        credential_service=None,  # type: ignore[arg-type]
        repository_service=None,  # type: ignore[arg-type]
        settings=AgentExecutionSettings(),
    )

    assert client_arguments["api_key"] == "ls-test"
    assert client_arguments["hide_inputs"] is True
    assert client_arguments["hide_outputs"] is True
