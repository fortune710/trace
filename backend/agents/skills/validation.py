"""Input validation and safe serialization for skills.sh skill identities."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

MAX_AGENT_SKILLS = 16
MAX_SKILL_ID_LENGTH = 256
_SKILL_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WELL_KNOWN_SOURCE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_GITHUB_SOURCE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,38}[A-Za-z0-9])?/[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99}[A-Za-z0-9])?$"
)
_FORBIDDEN_SKILL_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
    }
)
_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|authorization|cookie|credential|password|secret|token)",
    re.IGNORECASE,
)


class SkillValidationError(ValueError):
    """Raised when a skill identifier or payload fails validation."""


def normalize_skill_id(raw: str) -> str:
    skill_id = raw.strip().strip("/")
    if not skill_id or len(skill_id) > MAX_SKILL_ID_LENGTH:
        raise SkillValidationError("skill_id_invalid")
    if ".." in skill_id or "\\" in skill_id or "://" in skill_id:
        raise SkillValidationError("skill_id_invalid")
    parts = skill_id.split("/")
    if len(parts) == 2:
        source, slug = parts
        if not _WELL_KNOWN_SOURCE.fullmatch(source):
            raise SkillValidationError("skill_id_invalid")
    elif len(parts) == 3:
        source = f"{parts[0]}/{parts[1]}"
        slug = parts[2]
        if not _GITHUB_SOURCE.fullmatch(source):
            raise SkillValidationError("skill_id_invalid")
    else:
        raise SkillValidationError("skill_id_invalid")
    if not _SKILL_SEGMENT.fullmatch(slug):
        raise SkillValidationError("skill_id_invalid")
    return f"{source}/{slug}"


def skill_detail_path(skill_id: str) -> str:
    normalized = normalize_skill_id(skill_id)
    return f"/api/v1/skills/{normalized}"


def validate_search_query(query: str) -> str:
    cleaned = " ".join(query.split())
    if len(cleaned) < 2 or len(cleaned) > 200:
        raise SkillValidationError("search_query_invalid")
    return cleaned


def validate_public_https_url(url: str | None, *, field: str) -> str | None:
    if url is None:
        return None
    if not isinstance(url, str) or len(url) > 2048:
        raise SkillValidationError(f"{field}_invalid")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise SkillValidationError(f"{field}_invalid")
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise SkillValidationError(f"{field}_invalid")
    if host.startswith(("10.", "192.168.", "169.254.")):
        raise SkillValidationError(f"{field}_invalid")
    return url


def assert_no_sensitive_keys(payload: dict[str, Any]) -> None:
    for key in payload:
        if not isinstance(key, str):
            raise SkillValidationError("skill_payload_invalid")
        lowered = key.lower()
        if lowered in _FORBIDDEN_SKILL_KEYS or _SENSITIVE_KEY.search(key):
            raise SkillValidationError("skill_payload_unsafe")


def skill_snapshot_dict(
    *,
    skill_id: str,
    slug: str,
    name: str,
    source: str,
    source_type: str,
    install_url: str | None,
    url: str,
    content_hash: str | None,
    skill_md: str,
    files: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Build the JSON shape stored on agents.skills / review snapshots."""

    snapshot: dict[str, object] = {
        "provider": "skills.sh",
        "id": skill_id,
        "slug": slug,
        "name": name,
        "source": source,
        "source_type": source_type,
        "url": url,
        "skill_md": skill_md,
    }
    if install_url is not None:
        snapshot["install_url"] = install_url
    if content_hash is not None:
        snapshot["hash"] = content_hash
    if files:
        snapshot["files"] = files
    assert_no_sensitive_keys(snapshot)
    return snapshot


def is_skills_sh_skill(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("provider") == "skills.sh"
        and isinstance(value.get("id"), str)
    )


def skill_display_name(value: object, index: int = 0) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        skill_id = value.get("id")
        if isinstance(skill_id, str) and skill_id.strip():
            return skill_id.strip()
    return f"Configured skill {index + 1}"
