import pytest
from pydantic import ValidationError

from db.types import ModelProvider
from resources.schemas import AgentCreate, AgentSkillAttach, AgentUpdate
from reviews.models import ReviewCategory


def test_agent_create_rejects_client_supplied_skill_bodies() -> None:
    with pytest.raises(ValidationError):
        AgentCreate(
            name="reviewer",
            review_category=ReviewCategory.SECURITY,
            model_provider=ModelProvider.OPENAI,
            model_name="gpt-5.1",
            skills=[
                {
                    "provider": "skills.sh",
                    "id": "vercel-labs/skills/find-skills",
                    "skill_md": "sneaky",
                }
            ],
        )


def test_agent_update_allows_skill_id_references() -> None:
    update = AgentUpdate(
        skills=[{"provider": "skills.sh", "id": "vercel-labs/skills/find-skills"}]
    )
    assert update.skills == [
        {"provider": "skills.sh", "id": "vercel-labs/skills/find-skills"}
    ]


def test_agent_skill_attach_requires_skill_id() -> None:
    attached = AgentSkillAttach(skill_id="vercel-labs/skills/find-skills")
    assert attached.skill_id == "vercel-labs/skills/find-skills"
    with pytest.raises(ValidationError):
        AgentSkillAttach(skill_id="x")
