"""Account-owned agent templates and idempotent provisioning helpers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from agents.models import Agent
from auth.uuids import uuid7
from db.types import ReviewCategory


@dataclass(frozen=True)
class DefaultAgent:
    key: str
    name: str
    personality: str
    review_category: ReviewCategory
    avatar: str


DEFAULT_AGENTS: tuple[DefaultAgent, ...] = (
    DefaultAgent(
        key="harvey-specter-legal",
        name="Harvey Specter",
        personality=(
            "You are a decisive in-house legal reviewer. Identify concrete legal, "
            "privacy, compliance, and terms-of-service risk; distinguish required "
            "action from business judgment; and recommend plain-language mitigations."
        ),
        review_category=ReviewCategory.LEGAL,
        avatar="agent-defaults/harvey-specter",
    ),
    DefaultAgent(
        key="mark-zuckerberg-engineering",
        name="Mark Zuckerberg",
        personality=(
            "You are a systems-minded engineering reviewer. Examine architecture, "
            "reliability, security boundaries, scalability, and developer ergonomics; "
            "prioritize specific, reproducible fixes."
        ),
        review_category=ReviewCategory.ENGINEERING,
        avatar="agent-defaults/mark-zuckerberg",
    ),
    DefaultAgent(
        key="super-pm-product",
        name="Super PM",
        personality=(
            "You are a practical product strategist. Evaluate user value, onboarding, "
            "scope, edge cases, success metrics, and launch risk; turn ambiguity into "
            "clear priorities."
        ),
        review_category=ReviewCategory.PRODUCT,
        avatar="agent-defaults/super-pm",
    ),
)


def seed_default_agents(connection: Connection, *, owner_id: UUID) -> None:
    """Create missing defaults without changing an account's existing agents."""
    for agent in DEFAULT_AGENTS:
        statement = insert(Agent).values(
            id=uuid7(),
            owner_id=owner_id,
            name=agent.name,
            personality=agent.personality,
            review_category=agent.review_category,
            model_provider="openai",
            model_name="gpt-6.1-sol",
            avatar=agent.avatar,
            default_key=agent.key,
            skills=[],
        )
        connection.execute(
            statement.on_conflict_do_nothing(
                index_elements=["owner_id", "default_key"],
                index_where=Agent.default_key.is_not(None),
            )
        )


__all__ = ["DEFAULT_AGENTS", "DefaultAgent", "seed_default_agents"]
