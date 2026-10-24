"""Provider-neutral runtime agent definitions.

This module deliberately does not import the SQLAlchemy Agent model. Runtime
credentials exist only for the duration of a provider call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, SecretStr


class ToolDefinition(Protocol):
    """Reserved contract for a future executable agent tool."""

    name: str
    description: str


class FindingOutput(BaseModel):
    severity: str = Field(pattern="^(info|low|medium|high|critical)$")
    title: str = Field(min_length=1, max_length=500)
    explanation: str = Field(min_length=1, max_length=10_000)
    evidence: str | None = Field(default=None, max_length=10_000)
    source_location: str | None = Field(default=None, max_length=2_000)
    recommendation: str | None = Field(default=None, max_length=10_000)


class FindingBatch(BaseModel):
    findings: list[FindingOutput] = Field(default_factory=list, max_length=100)


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
    tools: tuple[ToolDefinition, ...] = ()

    def run(self, *, review_target: ReviewTarget) -> FindingBatch:
        """Review an immutable target without embedding repository content."""
        category = self.metadata.get("category", "engineering")
        personality = self.metadata.get("personality") or "Be precise and evidence-led."
        system_prompt = (
            f"You are Trace's {category} review agent. {personality}\n"
            "Use only your approved repository tools to inspect the specified "
            "immutable source revision. Do not infer source content or report a "
            "finding unless it is supported by evidence you read through a tool. "
            "Return only concrete launch risks. "
            "Each finding must include evidence and a repository-relative source "
            "location when available. Return no finding when there is no risk.\n"
        )
        human_message = (
            "Review target:\n"
            f"- source kind: {review_target.source_kind}\n"
            f"- source identifier: {review_target.source_identifier}\n"
            f"- immutable revision: {review_target.source_revision}\n\n"
            "Inspect this target with your repository tools before returning findings."
        )
        model = self._model().with_structured_output(FindingBatch)
        response = model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_message),
            ]
        )
        if isinstance(response, FindingBatch):
            return response
        return FindingBatch.model_validate(response)

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

            return ChatGoogleGenerativeAI(model=self.model, google_api_key=self.api_key)
        if self.provider == "xai":
            from langchain_xai import ChatXAI

            return ChatXAI(model=self.model, api_key=api_key)
        raise ValueError("provider_unsupported")

    def _provider_api_key(self) -> SecretStr:
        if not self.api_key:
            raise ValueError("model_access_unavailable")
        return SecretStr(self.api_key)
