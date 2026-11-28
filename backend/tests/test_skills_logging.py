from __future__ import annotations

import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from agents.skills.client import SkillsShClient, SkillsShConfigError
from agents.skills.config import SkillsSettings
from agents.skills.logging import (
    bind_skills_log_context,
    reset_skills_log_context,
    skills_log,
    skills_log_context,
    timed_step,
)


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


def test_skills_log_emits_json_and_redacts_forbidden_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="trace.skills")
    with skills_log_context(request_id="req-1", owner_id="owner-1"):
        skills_log(
            "agent_skill_attach",
            step="validation",
            skill_id="vercel-labs/skills/find-skills",
            proxy_secret="must-not-appear",
            skill_md="---\nsecret body\n",
            authorization="Bearer abc.def.ghi",
            token="should-drop",
            note="safe Bearer sk-abcdefghijklmnopqrstuvwxyz",
        )

    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].getMessage())
    assert payload["event"] == "agent_skill_attach"
    assert payload["request_id"] == "req-1"
    assert payload["owner_id"] == "owner-1"
    assert payload["skill_id"] == "vercel-labs/skills/find-skills"
    assert "proxy_secret" not in payload
    assert "skill_md" not in payload
    assert "authorization" not in payload
    assert "token" not in payload
    assert "[REDACTED]" in payload["note"]
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in payload["note"]


def test_skills_log_context_reset_does_not_leak() -> None:
    token = bind_skills_log_context(request_id="temp")
    reset_skills_log_context(token)
    with skills_log_context(request_id="kept"):
        skills_log("probe", step="request")


def test_unconfigured_transport_logs_distinct_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="trace.skills")
    client = SkillsShClient(
        _settings(oidc_token=None, proxy_url=None, proxy_secret=None),
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    with pytest.raises(SkillsShConfigError):
        client.curated_skills()

    payloads = [json.loads(record.getMessage()) for record in caplog.records]
    assert any(
        payload.get("error_code") == "skills_transport_unconfigured"
        and payload.get("transport") == "unconfigured"
        and payload.get("step") == "transport_config"
        for payload in payloads
    )
    for payload in payloads:
        assert "oidc_token" not in payload
        assert "proxy_secret" not in payload
        assert "Authorization" not in json.dumps(payload)


def test_skills_log_keeps_safe_diagnostic_flags(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="trace.skills")
    skills_log(
        "skills_transport_status",
        proxy_secret_configured=True,
        skill_md_chars=128,
        proxy_secret="must-not-appear",
        skill_md="---\nbody\n",
    )

    payload = json.loads(caplog.records[0].getMessage())
    assert payload["proxy_secret_configured"] is True
    assert payload["skill_md_chars"] == 128
    assert "proxy_secret" not in payload
    assert "skill_md" not in payload


def test_timed_step_emits_after_duration_and_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="trace.skills")
    with timed_step("agent_skill_attach", "size_check", skill_id="a/b/c") as fields:
        fields["skill_md_chars"] = 42

    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].getMessage())
    assert payload["event"] == "agent_skill_attach"
    assert payload["step"] == "size_check"
    assert payload["outcome"] == "success"
    assert payload["skill_md_chars"] == 42
    assert isinstance(payload["duration_ms"], float)
    assert payload["duration_ms"] >= 0


def test_timed_step_emits_finalized_error_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="trace.skills")
    with (
        pytest.raises(RuntimeError, match="boom"),
        timed_step("agent_skill_attach", "db_insert") as fields,
    ):
        fields["error_code"] = "agent_skill_conflict"
        raise RuntimeError("boom")

    payload = json.loads(caplog.records[0].getMessage())
    assert payload["outcome"] == "error"
    assert payload["error_code"] == "agent_skill_conflict"
    assert payload["error_type"] == "RuntimeError"
    assert isinstance(payload["duration_ms"], float)


def test_blank_base_url_keeps_string_default() -> None:
    settings = SkillsSettings(
        base_url="   ",
        oidc_token=None,
        proxy_url="https://example.com/api/skills-sh",
        proxy_secret=SecretStr("proxy-secret"),
    )
    assert settings.base_url == "https://skills.sh"
    assert settings.proxy_url == "https://example.com/api/skills-sh"


def test_proxy_success_logs_transport_and_upstream_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="trace.skills")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == "Bearer proxy-secret"
        return httpx.Response(
            200,
            json={"data": [], "count": 0},
            headers={
                "x-ratelimit-limit": "100",
                "x-ratelimit-remaining": "99",
                "retry-after": "",
            },
        )

    client = SkillsShClient(
        _settings(
            oidc_token=None,
            proxy_url="https://traceai.vercel.app/api/skills-sh",
            proxy_secret=SecretStr("proxy-secret"),
        ),
        transport=httpx.MockTransport(handler),
    )
    client.search_skills(query="react")

    payloads = [json.loads(record.getMessage()) for record in caplog.records]
    upstream = next(
        payload
        for payload in payloads
        if payload.get("event") == "skills_upstream_request"
        and payload.get("outcome") == "success"
    )
    assert upstream["transport"] == "proxy"
    assert upstream["upstream_path"] == "/api/v1/skills/search"
    assert upstream["upstream_status"] == 200
    assert upstream["x_ratelimit_limit"] == "100"
    assert upstream["x_ratelimit_remaining"] == "99"
    assert "proxy_secret" not in upstream
    assert "authorization" not in upstream
