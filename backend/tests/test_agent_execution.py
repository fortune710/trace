from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langchain_core.tools import ToolException
from pydantic import SecretStr, ValidationError

import agents.execution.agent as execution_agent_module
import agents.execution.executor as execution_executor_module
from agents.execution.agent import (
    Agent,
    FindingBatch,
    RemediationFindingOutput,
    ReviewFindingBatch,
    ReviewFindingOutput,
    ReviewTarget,
)
from agents.execution.executor import ReviewExecutionService, _source_failure_code
from agents.execution.orchestrator import OrchestratorAgent
from agents.execution.patches import (
    PatchIntentBatch,
)
from agents.execution.redaction import redact_text
from agents.execution.tools import (
    REPOSITORY_REVIEW_TOOLS,
    ToolExecutionContext,
    list_paths,
    search_code,
    validate_diff,
    validate_diff_for_review,
    web_search,
)
from auth.errors import (
    GithubAuthorizationRequired,
    ProviderRateLimited,
    ProviderUnavailable,
    RepositoryNotFound,
)
from external_repositories.service import ReviewSourceFileError
from notifications.models import NotificationEventType
from reviews.config import AgentExecutionSettings
from reviews.dispatch import _open_connection
from reviews.models import ReviewStatus


def _tool_context(tavily_api_key: SecretStr | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        owner_id=None,  # type: ignore[arg-type]
        source_kind="github",
        source_identifier="42",
        source_revision="a" * 40,
        repository_access=None,  # type: ignore[arg-type]
        review_id=UUID("00000000-0000-0000-0000-000000000001"),
        tavily_api_key=tavily_api_key,
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


def test_agent_has_repository_and_web_tools_by_default() -> None:
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
        "web_search",
    ]


def test_repository_tools_require_source_without_exposing_runtime_context() -> None:
    schemas = {
        tool.name: tool.tool_call_schema.model_json_schema()["properties"]
        for tool in REPOSITORY_REVIEW_TOOLS
    }

    assert set(schemas["list_paths"]) == {"source", "path_prefix", "max_results"}
    assert set(schemas["read_file"]) == {"source", "path"}
    assert set(schemas["search_code"]) == {"source", "query", "path_prefix"}
    assert set(schemas["web_search"]) == {"query"}
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
    assert "public research query" in schemas["web_search"]["query"]["description"]


def test_web_search_returns_bounded_cited_results_without_logging_query_or_key(
    monkeypatch, caplog
) -> None:
    calls: list[dict[str, object]] = []

    class FakeTavilyClient:
        def __init__(self, *, api_key: str) -> None:
            calls.append({"api_key": api_key})

        def search(self, query: str, **kwargs: object) -> dict[str, object]:
            calls.append({"query": query, **kwargs})
            return {
                "answer": "This must not be returned.",
                "results": [
                    {
                        "title": f"Result {index}",
                        "url": f"https://example.test/{index}",
                        "content": f"Snippet {index}",
                    }
                    for index in range(6)
                ],
            }

    monkeypatch.setattr("agents.execution.tools.TavilyClient", FakeTavilyClient)
    query = "Python dependency vulnerability guidance"
    key = "tvly-test-secret"

    with caplog.at_level("INFO", logger="trace.agent_execution.tools"):
        result = web_search.func(  # type: ignore[union-attr]
            query=query,
            runtime=SimpleNamespace(context=_tool_context(SecretStr(key))),
        )

    assert calls == [
        {"api_key": key},
        {
            "query": query,
            "search_depth": "basic",
            "topic": "general",
            "max_results": 5,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
        },
    ]
    assert result == {
        "results": [
            {
                "title": f"Result {index}",
                "url": f"https://example.test/{index}",
                "snippet": f"Snippet {index}",
            }
            for index in range(5)
        ]
    }
    assert query not in caplog.text
    assert key not in caplog.text


@pytest.mark.parametrize(
    "query",
    [
        "```python" + "\n" + "print('private source')" + "\n" + "```",
        "def private_function(): return secret",
        "line one" + "\n" + "line two",
    ],
)
def test_web_search_rejects_source_shaped_queries(query: str) -> None:
    with pytest.raises(ToolException, match="web_search_query_rejected"):
        web_search.func(  # type: ignore[union-attr]
            query=query,
            runtime=SimpleNamespace(
                context=_tool_context(SecretStr("tvly-test-secret"))
            ),
        )


def test_web_search_returns_safe_unavailable_errors(monkeypatch) -> None:
    runtime = SimpleNamespace(context=_tool_context())
    with pytest.raises(ToolException, match="web_search_unavailable"):
        web_search.func(query="public package release notes", runtime=runtime)  # type: ignore[union-attr]

    class FailingTavilyClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def search(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("provider response includes a secret")

    monkeypatch.setattr("agents.execution.tools.TavilyClient", FailingTavilyClient)
    with pytest.raises(ToolException, match="web_search_unavailable"):
        web_search.func(  # type: ignore[union-attr]
            query="public package release notes",
            runtime=SimpleNamespace(
                context=_tool_context(SecretStr("tvly-test-secret"))
            ),
        )

    class InvalidResponseTavilyClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def search(self, *_args: object, **_kwargs: object) -> object:
            return {"results": "not-a-list"}

    monkeypatch.setattr(
        "agents.execution.tools.TavilyClient", InvalidResponseTavilyClient
    )
    with pytest.raises(ToolException, match="web_search_unavailable"):
        web_search.func(  # type: ignore[union-attr]
            query="public package release notes",
            runtime=SimpleNamespace(
                context=_tool_context(SecretStr("tvly-test-secret"))
            ),
        )


def test_validate_diff_rejects_structurally_malformed_hunks_before_git() -> None:
    result = validate_diff_for_review(
        source="github",
        diff=(
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "+unexpected\n"
        ),
        context=_tool_context(),
    )

    assert result == {
        "valid": False,
        "level": "structure",
        "reason": "hunk_line_count_mismatch",
    }


def test_validate_diff_reports_invalid_hunk_line_location() -> None:
    result = validate_diff_for_review(
        source="github",
        diff=(
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "new-without-a-prefix\n"
            "+new\n"
        ),
        context=_tool_context(),
    )

    assert result == {
        "valid": False,
        "level": "structure",
        "reason": "invalid_hunk_line",
        "line_offset": 6,
        "hunk_number": 1,
    }


def test_validate_diff_runs_exact_revision_check_without_logging_source(caplog) -> None:
    class RepositoryAccess:
        def validate_diff(self, **kwargs):
            assert kwargs["diff"].startswith("diff --git")
            assert kwargs["log_context"].review_id
            return True

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
    diff = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with caplog.at_level("INFO", logger="trace.agent_execution.tools"):
        result = validate_diff.func(  # type: ignore[union-attr]
            source="github",
            diff=diff,
            runtime=runtime,
        )

    assert result == {"valid": True, "levels": ["structure", "safety", "apply"]}
    assert '"diff_bytes"' in caplog.text
    assert diff not in caplog.text


def test_list_paths_logs_arguments_and_a_result_summary(caplog) -> None:
    class RepositoryAccess:
        def list_paths(self, **kwargs):
            assert kwargs["path_prefix"] == "backend"
            assert kwargs["log_context"].review_id
            return ["backend/main.py", "backend/worker.py"], False, 3

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
        "skipped_paths": 3,
    }
    assert '"event": "repository_tool_started"' in caplog.text
    assert '"path_prefix": "backend"' in caplog.text
    assert '"path_count": 2' in caplog.text
    assert '"skipped_paths": 3' in caplog.text


def test_search_code_skips_unsearchable_files() -> None:
    class RepositoryAccess:
        def list_paths(self, **_kwargs):
            return ["assets/logo.png", ".claude-link", "src/app.py"], False, 7

        def read_file(self, *, path, **_kwargs):
            if path == "assets/logo.png":
                raise ReviewSourceFileError("file_not_utf8")
            if path == ".claude-link":
                raise ReviewSourceFileError("not_a_file")
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
        "skipped_paths": 7,
        "skipped_files": 2,
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
            return {"structured_response": ReviewFindingBatch()}

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
    assert create_agent_arguments["response_format"] is ReviewFindingBatch
    assert "approved tools" in create_agent_arguments["system_prompt"]
    assert (
        "Never include repository source text"
        in create_agent_arguments["system_prompt"]
    )
    assert "candidate navigation hints only" in create_agent_arguments["system_prompt"]
    assert "must never block the review" in create_agent_arguments["system_prompt"]
    assert (
        "research its plausible public impact"
        in create_agent_arguments["system_prompt"]
    )
    assert (
        "relevant CVEs, vendor advisories, regulatory fines"
        in create_agent_arguments["system_prompt"]
    )
    assert (
        "Do not invent or overstate impact" in create_agent_arguments["system_prompt"]
    )
    assert (
        "Format evidence as concise GitHub-Flavored Markdown"
        in create_agent_arguments["system_prompt"]
    )
    assert "prompt_text" in create_agent_arguments["system_prompt"]
    assert (
        "Reporting style: Be precise and evidence-led."
        in create_agent_arguments["system_prompt"]
    )
    assert "never narrows what you inspect" in create_agent_arguments["system_prompt"]
    assert (
        "Do not produce patches or calculate hashes"
        in create_agent_arguments["system_prompt"]
    )
    assert "after your findings are saved" in create_agent_arguments["system_prompt"]
    assert create_agent_arguments["context_schema"] is ToolExecutionContext
    assert messages[0].content == (
        "Review target:\n"
        "- source kind: gitlab\n"
        "- source identifier: group/project\n"
        f"- immutable revision: {'b' * 40}\n\n"
        "Inspect this target with your approved tools before returning findings."
    )


def test_review_saves_output_without_requiring_a_patch(monkeypatch) -> None:
    class Runtime:
        def invoke(self, inputs, *, context):
            return {
                "structured_response": ReviewFindingBatch(
                    findings=[
                        ReviewFindingOutput(
                            severity="high",
                            title="Missing authorization",
                            explanation="Evidence",
                            prompt_text="Add authorization.",
                        )
                    ]
                )
            }

    monkeypatch.setattr(Agent, "_model", lambda self: object())
    monkeypatch.setattr(
        execution_agent_module, "create_agent", lambda **kwargs: Runtime()
    )
    result = Agent(provider="openai", model="test").run(
        review_target=ReviewTarget("github", "123", "a" * 40),
        tool_context=_tool_context(),
    )
    assert len(result.findings) == 1
    assert "patch_intents" not in result.findings[0].model_dump()


def test_diff_specialist_preserves_correction_history(monkeypatch) -> None:
    from langchain_core.messages import AIMessage

    from agents.execution.agent import DiffAgent
    from agents.execution.patches import ReplaceEdit

    context = _tool_context()
    reference = context.register_source(path="app.py", content="old\n")
    calls = []
    submissions = []

    class Runtime:
        def invoke(self, inputs, *, context, config):
            calls.append(inputs["messages"])
            return {
                "messages": [*inputs["messages"], AIMessage(content="candidate edits")],
                "structured_response": PatchIntentBatch(
                    edits=[
                        ReplaceEdit(
                            source_ref="wrong" if len(calls) == 1 else reference,
                            start_line=1,
                            end_line=1,
                            replacement="new\n",
                        )
                    ]
                ),
            }

    monkeypatch.setattr(Agent, "_model", lambda self: object())
    monkeypatch.setattr(
        execution_agent_module, "create_agent", lambda **kwargs: Runtime()
    )
    result = DiffAgent(provider="openai", model="test").run(
        finding=ReviewFindingOutput(
            severity="high", title="Issue", explanation="Evidence", prompt_text="Fix"
        ),
        review_target=ReviewTarget(
            context.source_kind, context.source_identifier, context.source_revision
        ),
        tool_context=context,
        on_submission=lambda **values: submissions.append(values),
    )
    assert len(calls) == 2
    assert any(message.content == "candidate edits" for message in calls[1])
    assert "invalid_source_reference" in calls[1][-1].content
    assert submissions[0]["diagnostic"]["code"] == "invalid_source_reference"
    assert submissions[1]["diagnostic"] is None
    assert "@@ -1 +1 @@" in result.diff


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


def test_local_review_does_not_open_github_source_access(monkeypatch) -> None:
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
        id=uuid4(),
        source_identifier="workspace-123",
        source_revision="revision-123",
    )

    reader = object()
    service._engine = object()
    service._patch_store = SimpleNamespace(cipher=object())
    monkeypatch.setattr(
        "repository_intelligence.local_source.LocalReviewSourceAccess.open",
        lambda **kwargs: reader,
    )
    with service._open_review_source_access(  # type: ignore[arg-type]
        owner_id=uuid4(),
        review=review,
    ) as repository_access:
        assert repository_access is reader


def test_claiming_a_queued_review_creates_a_started_notification(monkeypatch) -> None:
    service = object.__new__(ReviewExecutionService)
    service._engine = object()
    owner_id = uuid4()
    review_id = uuid4()
    notifications: list[dict[str, object]] = []

    class StatusResult:
        def scalar_one_or_none(self):
            return ReviewStatus.QUEUED

    class UpdateResult:
        rowcount = 1

    class Connection:
        calls = 0

        def execute(self, _statement):
            self.calls += 1
            return StatusResult() if self.calls == 1 else UpdateResult()

    @contextmanager
    def fake_principal_transaction(_engine, _owner_id):
        yield Connection()

    monkeypatch.setattr(
        execution_executor_module,
        "principal_transaction",
        fake_principal_transaction,
    )
    monkeypatch.setattr(
        execution_executor_module,
        "create_notification",
        lambda _connection, **kwargs: notifications.append(kwargs),
    )

    assert service._claim_queued_review(owner_id=owner_id, review_id=review_id)
    assert notifications == [
        {
            "owner_id": owner_id,
            "event_type": NotificationEventType.REVIEW_STARTED,
            "dedupe_key": f"review:{review_id}:started",
            "review_id": review_id,
        }
    ]


def test_claiming_a_nonqueued_review_does_not_create_a_notification(
    monkeypatch,
) -> None:
    service = object.__new__(ReviewExecutionService)
    service._engine = object()
    notifications: list[dict[str, object]] = []

    class Connection:
        def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: ReviewStatus.RUNNING)

    @contextmanager
    def fake_principal_transaction(_engine, _owner_id):
        yield Connection()

    monkeypatch.setattr(
        execution_executor_module,
        "principal_transaction",
        fake_principal_transaction,
    )
    monkeypatch.setattr(
        execution_executor_module,
        "create_notification",
        lambda _connection, **kwargs: notifications.append(kwargs),
    )

    assert not service._claim_queued_review(owner_id=uuid4(), review_id=uuid4())
    assert notifications == []


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


def test_execution_service_langsmith_redaction_is_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("REVIEW_RABBITMQ_URL", "amqp://guest:guest@localhost/")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setenv("LANGSMITH_HIDE_INPUTS", "false")
    monkeypatch.setenv("LANGSMITH_HIDE_OUTPUTS", "false")
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

    assert client_arguments["hide_inputs"] is False
    assert client_arguments["hide_outputs"] is False
