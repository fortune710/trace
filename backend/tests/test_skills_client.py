from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from agents.skills.client import (
    SkillsShAuthError,
    SkillsShClient,
    SkillsShNotFoundError,
    SkillsShRateLimitError,
)
from agents.skills.config import SkillsSettings


def _settings(**overrides: object) -> SkillsSettings:
    values = {
        "base_url": "https://skills.sh",
        "oidc_token": SecretStr("test-oidc-token"),
        "proxy_url": None,
        "proxy_secret": None,
        "timeout_seconds": 5.0,
        "max_skill_md_chars": 200_000,
        "max_files": 32,
        "max_file_chars": 100_000,
    }
    values.update(overrides)
    return SkillsSettings(**values)


def test_get_skill_normalizes_detail_and_sends_bearer_token() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "id": "vercel-labs/skills/find-skills",
                "source": "vercel-labs/skills",
                "slug": "find-skills",
                "name": "find-skills",
                "sourceType": "github",
                "installs": 10,
                "installUrl": "https://github.com/vercel-labs/skills",
                "url": "https://skills.sh/vercel-labs/skills/find-skills",
                "hash": "abc",
                "files": [
                    {"path": "SKILL.md", "contents": "---\nname: find-skills\n"},
                ],
            },
        )

    client = SkillsShClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    detail = client.get_skill("vercel-labs/skills/find-skills")

    assert captured["authorization"] == "Bearer test-oidc-token"
    assert "skills.sh/api/v1/skills/vercel-labs/skills/find-skills" in str(
        captured["url"]
    )
    assert detail["skill_md"].startswith("---")
    assert detail["id"] == "vercel-labs/skills/find-skills"


def test_client_maps_auth_and_rate_limit_errors() -> None:
    def unauthorized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = SkillsShClient(
        _settings(),
        transport=httpx.MockTransport(unauthorized),
    )
    with pytest.raises(SkillsShAuthError):
        client.search_skills(query="react")

    def limited(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "12"},
            json={"error": "rate_limited"},
        )

    limited_client = SkillsShClient(
        _settings(),
        transport=httpx.MockTransport(limited),
    )
    with pytest.raises(SkillsShRateLimitError) as error:
        limited_client.list_skills()
    assert error.value.retry_after == 12


def test_client_rejects_missing_skill_md() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "vercel-labs/skills/find-skills",
                "source": "vercel-labs/skills",
                "slug": "find-skills",
                "files": [{"path": "README.md", "contents": "nope"}],
                "url": "https://skills.sh/vercel-labs/skills/find-skills",
            },
        )

    client = SkillsShClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    from agents.skills.client import SkillsShError

    with pytest.raises(SkillsShError):
        client.get_skill("vercel-labs/skills/find-skills")


def test_proxy_mode_uses_shared_secret_not_oidc_header() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "data": [],
                    "query": "react",
                    "searchType": "fuzzy",
                    "count": 0,
                }
            ),
            headers={"content-type": "application/json"},
        )

    client = SkillsShClient(
        _settings(
            oidc_token=None,
            proxy_url="https://traceai.vercel.app/api/skills-sh",
            proxy_secret=SecretStr("proxy-secret"),
        ),
        transport=httpx.MockTransport(handler),
    )
    payload = client.search_skills(query="react")
    assert payload["count"] == 0
    assert captured["authorization"] == "Bearer proxy-secret"
    assert str(captured["url"]).startswith(
        "https://traceai.vercel.app/api/skills-sh/api/v1/skills/search"
    )


def test_not_found_mapping() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found"})

    client = SkillsShClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SkillsShNotFoundError):
        client.get_skill("vercel-labs/skills/missing")
