"""LangGraph supervisor for the immutable agents selected for a review."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents.execution.agent import Agent, FindingBatch, ReviewTarget
from agents.execution.tools import ToolExecutionContext


class ReviewGraphState(TypedDict):
    """State owned by the orchestrator agent."""

    review_target: ReviewTarget
    tool_context: ToolExecutionContext
    agents: tuple[Agent, ...]
    results: Annotated[list[FindingBatch], operator.add]


class ReviewSubagentState(TypedDict):
    """The isolated state passed to one spawned review subagent."""

    review_target: ReviewTarget
    tool_context: ToolExecutionContext
    agent: Agent


class OrchestratorAgent:
    """Spawns one LangGraph subagent for each immutable selected agent."""

    def __init__(self) -> None:
        graph = StateGraph(ReviewGraphState)
        graph.add_node("run_review_subagent", self._run_review_subagent)
        graph.add_conditional_edges(START, self._spawn_review_subagents)
        graph.add_edge("run_review_subagent", END)
        self._graph = graph.compile()

    def run(
        self,
        *,
        review_target: ReviewTarget,
        tool_context: ToolExecutionContext,
        agents: tuple[Agent, ...],
    ) -> list[FindingBatch]:
        """Delegate the prepared source to exactly the selected runtime agents."""
        state = self._graph.invoke(
            {
                "review_target": review_target,
                "tool_context": tool_context,
                "agents": agents,
                "results": [],
            }
        )
        return state["results"]

    @staticmethod
    def _spawn_review_subagents(state: ReviewGraphState) -> list[Send]:
        """Fan out work without the orchestrator invoking review agents itself."""
        return [
            Send(
                "run_review_subagent",
                {
                    "review_target": state["review_target"],
                    "tool_context": state["tool_context"],
                    "agent": agent,
                },
            )
            for agent in state["agents"]
        ]

    @staticmethod
    def _run_review_subagent(
        state: ReviewSubagentState,
    ) -> dict[str, list[FindingBatch]]:
        """Return this subagent's validated findings to the orchestrator."""
        return {
            "results": [
                state["agent"].run(
                    review_target=state["review_target"],
                    tool_context=state["tool_context"],
                )
            ]
        }


# Preserve the initial public name for callers that adopted it before the
# supervisor implementation landed.
ReviewOrchestrator = OrchestratorAgent
