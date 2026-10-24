from __future__ import annotations

import agents.execution.agent as execution_agent_module
from agents.execution.agent import Agent, FindingBatch, FindingOutput, ReviewTarget
from agents.execution.orchestrator import OrchestratorAgent
from agents.execution.redaction import redact_text
from agents.execution.tools import REPOSITORY_REVIEW_TOOLS, ToolExecutionContext
from reviews.config import AgentExecutionSettings


def _tool_context() -> ToolExecutionContext:
    return ToolExecutionContext(
        owner_id=None,  # type: ignore[arg-type]
        source_kind="github",
        source_identifier="42",
        source_revision="a" * 40,
        repository_service=None,  # type: ignore[arg-type]
    )


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
                FindingOutput(
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


def test_execution_settings_require_langsmith(monkeypatch) -> None:
    monkeypatch.setenv("REVIEW_RABBITMQ_URL", "amqp://guest:guest@localhost/")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")

    settings = AgentExecutionSettings()

    settings.validate_for_execution()
