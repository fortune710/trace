"""Provider-neutral LangChain agent definitions for review execution.

This module deliberately does not import the SQLAlchemy Agent model. Runtime
credentials exist only for the duration of a provider call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, SecretStr

from agents.execution.tools import REPOSITORY_REVIEW_TOOLS, ToolExecutionContext

type ToolDefinition = BaseTool | Callable[..., Any] | dict[str, Any]


class FindingOutput(BaseModel):
    severity: str = Field(pattern="^(info|low|medium|high|critical)$")
    title: str = Field(min_length=1, max_length=500)
    explanation: str = Field(min_length=1, max_length=10_000)
    evidence: str | None = Field(default=None, max_length=10_000)
    source_location: str | None = Field(default=None, max_length=2_000)
    recommendation: str | None = Field(default=None, max_length=10_000)


class RemediationFindingOutput(FindingOutput):
    prompt_text: str = Field(min_length=1, max_length=10_000)
    diff: str = Field(min_length=1, max_length=1_048_576)


class FindingBatch(BaseModel):
    findings: list[RemediationFindingOutput] = Field(
        default_factory=list,
        max_length=100,
    )


@dataclass(frozen=True, slots=True)
class ReviewTarget:
    """The immutable repository target an agent must inspect with tools."""

    source_kind: str
    source_identifier: str
    source_revision: str


@dataclass(frozen=True, slots=True)
class Agent:
    provider: str
    model: str
    skills: tuple[object, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    api_key: str | None = field(default=None, repr=False)
    tools: tuple[ToolDefinition, ...] = REPOSITORY_REVIEW_TOOLS

    def run(
        self,
        *,
        review_target: ReviewTarget,
        tool_context: ToolExecutionContext,
    ) -> FindingBatch:
        """Run a LangChain agent against an immutable, tool-inspected target."""
        category = self.metadata.get("category", "engineering")
        personality = self.metadata.get("personality") or "Be precise and evidence-led."
        system_prompt = (
            f"You are Trace's {category} review agent. {personality}\n"
            "Use only your approved repository tools to inspect the specified "
            "immutable source revision. Do not infer source content or report a "
            "finding unless it is supported by evidence you read through a tool. "
            "Return only concrete launch risks. "
            "Each finding must include evidence and a repository-relative source "
            "location when available. For every finding, also return:\n"
            "- prompt_text: a concise, implementation-ready prompt for a coding "
            "agent to resolve the finding in this exact repository revision.\n"
            "- diff: a complete Git unified diff for that fix, including diff --git, "
            "---, +++, and @@ hunk headers. The diff must modify only repository "
            "files you inspected through the approved tools.\n"
            "Return no finding when there is no risk."
        )
        human_message = (
            "Review target:\n"
            f"- source kind: {review_target.source_kind}\n"
            f"- source identifier: {review_target.source_identifier}\n"
            f"- immutable revision: {review_target.source_revision}\n\n"
            "Inspect this target with your repository tools before returning findings."
        )
        review_agent = create_agent(
            model=self._model(),
            tools=list(self.tools),
            system_prompt=system_prompt,
            response_format=FindingBatch,
            context_schema=ToolExecutionContext,
        )
        result = review_agent.invoke(
            {"messages": [HumanMessage(content=human_message)]},
            context=tool_context,
        )
        structured_response = result.get("structured_response")
        if structured_response is None:
            raise ValueError("model_output_invalid")
        return FindingBatch.model_validate(structured_response)

    def _model(self):
        api_key = self._provider_api_key()
        if self.provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=self.model, api_key=api_key)
        if self.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model_name=self.model,
                api_key=api_key,
                timeout=None,
                stop=None,
            )
        if self.provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(model=self.model, google_api_key=api_key)
        if self.provider == "xai":
            from langchain_xai import ChatXAI

            return ChatXAI(model=self.model, api_key=api_key)
        raise ValueError("provider_unsupported")

    def _provider_api_key(self) -> SecretStr:
        if not self.api_key:
            raise ValueError("model_access_unavailable")
        return SecretStr(self.api_key)
