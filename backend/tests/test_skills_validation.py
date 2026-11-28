import pytest

from agents.skills.validation import (
    SkillValidationError,
    normalize_skill_id,
    skill_snapshot_dict,
    validate_search_query,
)


def test_normalize_skill_id_accepts_github_and_well_known_forms() -> None:
    assert (
        normalize_skill_id("vercel-labs/skills/find-skills")
        == "vercel-labs/skills/find-skills"
    )
    assert normalize_skill_id("mintlify.com/mintlify") == "mintlify.com/mintlify"


@pytest.mark.parametrize(
    "skill_id",
    [
        "",
        "../etc/passwd",
        "https://evil.example/skill",
        "one/two/three/four",
        "bad source/skills/name",
        "owner/repo/bad slug!",
    ],
)
def test_normalize_skill_id_rejects_unsafe_values(skill_id: str) -> None:
    with pytest.raises(SkillValidationError):
        normalize_skill_id(skill_id)


def test_search_query_bounds() -> None:
    assert validate_search_query("  react  native ") == "react native"
    with pytest.raises(SkillValidationError):
        validate_search_query("a")


def test_skill_snapshot_builds_safe_payload() -> None:
    snapshot = skill_snapshot_dict(
        skill_id="vercel-labs/skills/find-skills",
        slug="find-skills",
        name="find-skills",
        source="vercel-labs/skills",
        source_type="github",
        install_url="https://github.com/vercel-labs/skills",
        url="https://skills.sh/vercel-labs/skills/find-skills",
        content_hash="abc",
        skill_md="---\nname: test\n",
        files=[{"path": "SKILL.md", "contents": "---\nname: test\n"}],
    )
    assert snapshot["provider"] == "skills.sh"
    assert snapshot["skill_md"].startswith("---")
    assert "api_key" not in snapshot
