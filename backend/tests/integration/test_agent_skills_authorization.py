from __future__ import annotations

from typing import Any

import pytest

from agents.skills.client import SkillsShClient

pytestmark = pytest.mark.integration


def _normalized_detail() -> dict[str, Any]:
    return {
        "id": "vercel-labs/skills/find-skills",
        "slug": "find-skills",
        "name": "find-skills",
        "source": "vercel-labs/skills",
        "source_type": "github",
        "installs": 42,
        "install_url": "https://github.com/vercel-labs/skills",
        "url": "https://skills.sh/vercel-labs/skills/find-skills",
        "hash": "abc123",
        "skill_md": "---\nname: find-skills\ndescription: Find skills.\n",
        "files": [
            {
                "path": "SKILL.md",
                "contents": "---\nname: find-skills\ndescription: Find skills.\n",
            }
        ],
    }


def test_owner_can_attach_and_foreign_owner_is_denied(
    account_pair,
    agent_factory,
    monkeypatch,
) -> None:
    owner, other = account_pair
    agent = agent_factory(owner)

    monkeypatch.setattr(
        SkillsShClient,
        "search_skills",
        lambda self, **kwargs: {
            "data": [
                {
                    "id": "vercel-labs/skills/find-skills",
                    "slug": "find-skills",
                    "name": "find-skills",
                    "source": "vercel-labs/skills",
                    "installs": 42,
                    "sourceType": "github",
                    "installUrl": "https://github.com/vercel-labs/skills",
                    "url": "https://skills.sh/vercel-labs/skills/find-skills",
                }
            ],
            "query": "find",
            "searchType": "fuzzy",
            "count": 1,
        },
    )
    monkeypatch.setattr(
        SkillsShClient,
        "get_skill",
        lambda self, skill_id: _normalized_detail(),
    )

    search = owner.request("GET", "/api/v1/skills/search?q=find")
    assert search.status_code == 200
    assert search.json()["data"][0]["id"] == "vercel-labs/skills/find-skills"

    attached = owner.request(
        "POST",
        f"/api/v1/agents/{agent['id']}/skills",
        json={"skill_id": "vercel-labs/skills/find-skills"},
    )
    assert attached.status_code == 201
    assert attached.json()["skill_id"] == "vercel-labs/skills/find-skills"

    details = owner.request("GET", f"/api/v1/agents/{agent['id']}")
    assert details.status_code == 200
    skills = details.json()["skills"]
    assert skills[0]["provider"] == "skills.sh"
    assert "skill_md" in skills[0]

    denied = other.request(
        "POST",
        f"/api/v1/agents/{agent['id']}/skills",
        json={"skill_id": "vercel-labs/skills/find-skills"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "authorization_denied"

    foreign_list = other.request("GET", f"/api/v1/agents/{agent['id']}/skills")
    assert foreign_list.status_code == 403

    removed = owner.request(
        "DELETE",
        f"/api/v1/agents/{agent['id']}/skills/vercel-labs/skills/find-skills",
    )
    assert removed.status_code == 204
