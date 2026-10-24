from __future__ import annotations

from agents.execution.orchestrator import OrchestratorAgent
from agents.execution.redaction import redact_text
from agents.execution.runtime import Agent, FindingBatch, FindingOutput, ReviewTarget
from reviews.config import AgentExecutionSettings


def test_agent_has_no_tools_by_default() -> None:
    agent = Agent(
        provider="openai",
        model="gpt-6.1-sol",
        skills=(),
        metadata={"category": "security", "personality": "Careful."},
    )

    assert agent.tools == ()


def test_agent_prompt_identifies_the_tool_inspected_review_target(monkeypatch) -> None:
    messages = []

    class StructuredOutputModel:
        def invoke(self, received_messages):
            messages.extend(received_messages)
            return FindingBatch()

    class Model:
        def with_structured_output(self, _schema):
            return StructuredOutputModel()

    monkeypatch.setattr(Agent, "_model", lambda _agent: Model())

    Agent(provider="openai", model="test-model").run(
        review_target=ReviewTarget(
            source_kind="gitlab",
            source_identifier="group/project",
            source_revision="b" * 40,
        )
    )

    assert "repository tools" in messages[0].content
    assert messages[1].content == (
        "Review target:\n"
        "- source kind: gitlab\n"
        "- source identifier: group/project\n"
        f"- immutable revision: {'b' * 40}\n\n"
        "Inspect this target with your repository tools before returning findings."
    )


def test_orchestrator_runs_only_supplied_agents(monkeypatch) -> None:
    invoked: list[str] = []

    def fake_run(self, *, review_target: ReviewTarget) -> FindingBatch:
        invoked.append(self.model)
        assert review_target.source_identifier == "workspace-123"
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
