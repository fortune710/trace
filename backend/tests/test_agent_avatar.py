from __future__ import annotations

import json
from base64 import urlsafe_b64encode
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from avatar_fixtures import make_png
from fastapi import FastAPI
from fastapi.testclient import TestClient

import resources.routes as resource_routes
from agents.avatar import (
    MAX_AVATAR_BYTES,
    AvatarRejected,
    parse_avatar_config,
    validate_avatar_png,
)
from agents.avatar_storage import StoredAvatar, avatar_url
from auth.config import AuthSettings
from auth.csrf import issue_csrf_token
from auth.errors import (
    AuthorizationDenied,
    ResourceNotFound,
    install_auth_error_handlers,
)
from auth.principal import AuthenticatedPrincipal, get_current_principal
from resources.routes import install_resource_routes

SETTINGS = AuthSettings(
    csrf_hmac_key=urlsafe_b64encode(b"d" * 32).decode("ascii").rstrip("="),  # type: ignore[arg-type]
)
PNG = make_png(256)


def _reason(error: pytest.ExceptionInfo[AvatarRejected]) -> tuple[int, str]:
    return error.value.status_code, error.value.reason


def test_validator_accepts_a_square_png() -> None:
    validate_avatar_png("image/png", PNG)
    validate_avatar_png("IMAGE/PNG; charset=binary", make_png(1))
    validate_avatar_png("image/png", make_png(512))


@pytest.mark.parametrize("content_type", [None, "", "image/jpeg", "text/plain"])
def test_validator_rejects_other_content_types(content_type: str | None) -> None:
    with pytest.raises(AvatarRejected) as error:
        validate_avatar_png(content_type, PNG)
    assert _reason(error) == (415, "avatar_type_unsupported")


def test_validator_enforces_the_size_cap() -> None:
    at_limit = make_png(16, pad=MAX_AVATAR_BYTES - len(make_png(16)) - 12 - 2)
    assert len(at_limit) == MAX_AVATAR_BYTES
    validate_avatar_png("image/png", at_limit)

    with pytest.raises(AvatarRejected) as error:
        validate_avatar_png("image/png", at_limit + b"\x00")
    assert _reason(error) == (413, "avatar_too_large")


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a png at all",
        b"\xff\xd8\xff\xe0" + b"\x00" * 64,
        PNG[:-12],
        PNG + b"trailing",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
    ],
)
def test_validator_rejects_non_png_or_truncated_bytes(data: bytes) -> None:
    with pytest.raises(AvatarRejected) as error:
        validate_avatar_png("image/png", data)
    assert _reason(error) == (400, "avatar_not_png")


def test_validator_rejects_a_corrupt_ihdr() -> None:
    corrupted = bytearray(PNG)
    corrupted[18] ^= 0xFF
    with pytest.raises(AvatarRejected) as error:
        validate_avatar_png("image/png", bytes(corrupted))
    assert _reason(error) == (400, "avatar_not_png")


def test_validator_requires_a_square_image() -> None:
    with pytest.raises(AvatarRejected) as error:
        validate_avatar_png("image/png", make_png(64, 32))
    assert _reason(error) == (400, "avatar_not_square")


def test_validator_bounds_the_dimensions() -> None:
    with pytest.raises(AvatarRejected) as error:
        validate_avatar_png("image/png", make_png(513))
    assert _reason(error) == (400, "avatar_dimensions_invalid")


def test_config_is_optional() -> None:
    assert parse_avatar_config(None) is None
    assert parse_avatar_config("") is None


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "eyes": "variant03",
        "brows": "variant07",
        "nose": "variant04",
        "lips": "variant09",
        "hair": "variant21",
        "body": "variant12",
        "backgroundColor": "#b6e3f4",
        "flip": False,
    }
    config.update(overrides)
    return {key: value for key, value in config.items() if value is not None}


def test_config_accepts_the_editor_options() -> None:
    full = _config(glasses="variant11", beard="variant12", flip=True)
    assert parse_avatar_config(json.dumps(full)) == full

    # Glasses and beard are omitted by the editor when switched off.
    without_optional = _config()
    assert "glasses" not in without_optional
    assert "beard" not in without_optional
    assert parse_avatar_config(json.dumps(without_optional)) == without_optional

    maximum = _config(
        eyes="variant05",
        brows="variant13",
        nose="variant20",
        lips="variant30",
        hair="variant63",
        body="variant25",
    )
    assert parse_avatar_config(json.dumps(maximum)) == maximum


@pytest.mark.parametrize(
    "overrides",
    [
        {"gesture": "variant01"},
        {"unknown": "variant01"},
        {"hair": "hat"},
        {"hair": "variant00"},
        {"hair": "variant64"},
        {"eyes": "variant06"},
        {"brows": "variant14"},
        {"nose": "variant21"},
        {"lips": "variant31"},
        {"body": "variant26"},
        {"glasses": "variant12"},
        {"beard": "variant13"},
        {"eyes": "happy"},
        {"eyes": "variant1"},
        {"eyes": "variant001"},
        {"eyes": "variant01\n"},
        {"eyes": 3},
        {"eyes": True},
        {"eyes": ["variant01"]},
        {"eyes": {"nested": "variant01"}},
        {"glasses": ""},
        {"backgroundColor": "red"},
        {"backgroundColor": "b6e3f4"},
        {"backgroundColor": "#B6E3F4"},
        {"backgroundColor": "#12345"},
        {"backgroundColor": "#1234567"},
        {"backgroundColor": "variant01"},
        {"flip": "true"},
        {"flip": 1},
    ],
)
def test_config_rejects_unknown_keys_and_bad_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(AvatarRejected) as error:
        parse_avatar_config(json.dumps(_config(**overrides)))
    assert _reason(error) == (400, "avatar_config_invalid")


@pytest.mark.parametrize("missing", ["eyes", "brows", "nose", "lips", "hair", "body"])
def test_config_requires_the_core_parts(missing: str) -> None:
    with pytest.raises(AvatarRejected) as error:
        parse_avatar_config(json.dumps(_config(**{missing: None})))
    assert _reason(error) == (400, "avatar_config_invalid")


@pytest.mark.parametrize(
    "raw", ["{}", "[]", '"variant01"', "null", "42", "{not json", "true"]
)
def test_config_rejects_non_objects_bad_json_and_empty_objects(raw: str) -> None:
    with pytest.raises(AvatarRejected) as error:
        parse_avatar_config(raw)
    assert _reason(error) == (400, "avatar_config_invalid")


def test_config_rejects_oversized_documents() -> None:
    raw = json.dumps({**_config(), "pad": "x" * 1100})
    with pytest.raises(AvatarRejected) as error:
        parse_avatar_config(raw)
    assert _reason(error) == (400, "avatar_config_too_large")


def test_avatar_url_carries_the_short_content_hash() -> None:
    agent_id = uuid4()
    digest = "0123456789abcdef" * 4
    assert (
        avatar_url(agent_id, digest)
        == f"/api/v1/agents/{agent_id}/avatar?v=0123456789ab"
    )


class FakeAgentService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.avatar: StoredAvatar | None = None
        self.error: Exception | None = None

    def set_avatar(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(("set_avatar", kwargs))
        if self.error is not None:
            raise self.error
        return {
            "id": kwargs["agent_id"],
            "name": "Agent",
            "personality": None,
            "review_category": "security",
            "model_provider": "openai",
            "model_name": "gpt-6.1-sol",
            "avatar": avatar_url(kwargs["agent_id"], "ab" * 32),
            "avatar_config": kwargs["config"],
            "skills": [],
            "credential_id": None,
            "configuration_version": 2,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "disabled_at": None,
        }

    def clear_avatar(self, **kwargs: Any) -> None:
        self.calls.append(("clear_avatar", kwargs))
        if self.error is not None:
            raise self.error

    def read_public_avatar(self, **kwargs: Any) -> StoredAvatar | None:
        self.calls.append(("read_public_avatar", kwargs))
        return self.avatar


class Harness:
    def __init__(
        self,
        client: TestClient,
        service: FakeAgentService,
        user_id: UUID,
        session_id: UUID,
    ) -> None:
        self.client = client
        self.service = service
        self.user_id = user_id
        self.csrf = issue_csrf_token(session_id=session_id, key=b"d" * 32)
        self.rate_limit_policies: list[str] = []

    def csrf_headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}

    def upload(
        self,
        *,
        agent_id: UUID | None = None,
        file: tuple[str, bytes, str] | None = ("avatar.png", PNG, "image/png"),
        config: str | None = None,
        csrf: bool = True,
    ):
        self.client.cookies.set(SETTINGS.csrf_cookie_name, self.csrf)
        return self.client.post(
            f"/agents/{agent_id or uuid4()}/avatar",
            files={"file": file} if file else None,
            data={"config": config} if config is not None else None,
            headers=self.csrf_headers() if csrf else {},
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    service = FakeAgentService()
    policies: list[str] = []

    async def record_rate_limit(limiter: object, *, policy: Any, subject: str) -> None:
        policies.append(policy.name)

    monkeypatch.setattr(resource_routes, "AgentService", lambda _engine: service)
    monkeypatch.setattr(resource_routes, "get_engine", lambda: object())
    monkeypatch.setattr(resource_routes, "rate_limiter_from_settings", lambda _: None)
    monkeypatch.setattr(resource_routes, "enforce_rate_limit", record_rate_limit)

    app = FastAPI()
    install_auth_error_handlers(app)
    install_resource_routes(app, SETTINGS)
    user_id, session_id = uuid4(), uuid4()
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        user_id=user_id, session_id=session_id
    )
    with TestClient(app) as client:
        result = Harness(client, service, user_id, session_id)
        result.rate_limit_policies = policies
        yield result


def test_upload_stores_the_png_and_returns_the_agent(harness: Harness) -> None:
    agent_id = uuid4()
    config = _config(glasses="variant02")

    response = harness.upload(agent_id=agent_id, config=json.dumps(config))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(agent_id)
    assert body["avatar"] == f"/api/v1/agents/{agent_id}/avatar?v=" + "ab" * 6
    assert body["avatar_config"] == config
    name, call = harness.service.calls[0]
    assert name == "set_avatar"
    assert call == {
        "owner_id": harness.user_id,
        "agent_id": agent_id,
        "content_type": "image/png",
        "data": PNG,
        "config": config,
    }
    assert harness.rate_limit_policies == ["resource.avatar_write.user"]


def test_upload_without_config_clears_the_stored_config(harness: Harness) -> None:
    response = harness.upload()

    assert response.status_code == 200
    assert response.json()["avatar_config"] is None
    assert harness.service.calls[0][1]["config"] is None


def test_replacing_an_avatar_is_an_idempotent_second_upload(harness: Harness) -> None:
    agent_id = uuid4()
    first = harness.upload(
        agent_id=agent_id, config=json.dumps(_config(eyes="variant01"))
    )
    second = harness.upload(
        agent_id=agent_id,
        file=("avatar.png", make_png(128), "image/png"),
        config=json.dumps(_config(eyes="variant02")),
    )

    assert first.status_code == second.status_code == 200
    assert [call[1]["config"] for call in harness.service.calls] == [
        _config(eyes="variant01"),
        _config(eyes="variant02"),
    ]


@pytest.mark.parametrize(
    ("file", "status_code"),
    [
        (("avatar.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "image/jpeg"), 415),
        (("avatar.png", b"definitely not a png", "image/png"), 400),
        (("avatar.png", make_png(64, 32), "image/png"), 400),
        (("avatar.png", make_png(600), "image/png"), 400),
        (("avatar.png", make_png(16, pad=MAX_AVATAR_BYTES), "image/png"), 413),
    ],
)
def test_upload_rejects_bad_files_without_storing(
    harness: Harness, file: tuple[str, bytes, str], status_code: int
) -> None:
    response = harness.upload(file=file)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == "invalid_request"
    assert harness.service.calls == []


def test_upload_requires_a_file(harness: Harness) -> None:
    response = harness.upload(file=None, config="{}")

    assert response.status_code == 400
    assert harness.service.calls == []


@pytest.mark.parametrize(
    "config",
    [
        json.dumps(_config(hat="variant01")),
        json.dumps(_config(eyes="wide")),
        json.dumps(_config(gesture="variant01")),
        '{"eyes": "variant01"}',
        "{broken",
        "[]",
        '{"pad": "' + "x" * 1100 + '"}',
    ],
)
def test_upload_rejects_invalid_config_without_storing(
    harness: Harness, config: str
) -> None:
    response = harness.upload(config=config)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert harness.service.calls == []


def test_upload_and_delete_require_a_csrf_token(harness: Harness) -> None:
    rejected_upload = harness.upload(csrf=False)
    rejected_delete = harness.client.delete(f"/agents/{uuid4()}/avatar")

    assert rejected_upload.status_code == 403
    assert rejected_upload.json()["error"]["code"] == "csrf_validation_failed"
    assert rejected_delete.status_code == 403
    assert harness.service.calls == []


def test_upload_surfaces_authorization_failures(harness: Harness) -> None:
    harness.service.error = AuthorizationDenied()
    assert harness.upload().status_code == 403

    harness.service.error = ResourceNotFound()
    assert harness.upload().status_code == 404


def test_delete_clears_the_avatar(harness: Harness) -> None:
    agent_id = uuid4()
    harness.client.cookies.set(SETTINGS.csrf_cookie_name, harness.csrf)

    response = harness.client.delete(
        f"/agents/{agent_id}/avatar", headers=harness.csrf_headers()
    )

    assert response.status_code == 204
    assert response.content == b""
    assert harness.service.calls == [
        ("clear_avatar", {"owner_id": harness.user_id, "agent_id": agent_id})
    ]
    assert harness.rate_limit_policies == ["resource.avatar_write.user"]


def test_public_get_serves_cacheable_bytes_without_authentication(
    harness: Harness,
) -> None:
    app = harness.client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides.clear()  # no principal, no cookies
    harness.service.avatar = StoredAvatar("image/png", PNG, "ab" * 32)
    agent_id = uuid4()

    response = harness.client.get(f"/agents/{agent_id}/avatar")

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["etag"] == '"' + "ab" * 32 + '"'
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert harness.service.calls == [("read_public_avatar", {"agent_id": agent_id})]
    assert harness.rate_limit_policies == []


def test_public_get_answers_conditional_requests(harness: Harness) -> None:
    harness.service.avatar = StoredAvatar("image/png", PNG, "ab" * 32)
    etag = '"' + "ab" * 32 + '"'

    for header in (etag, f"W/{etag}", f'"other", {etag}', "*"):
        response = harness.client.get(
            f"/agents/{uuid4()}/avatar", headers={"If-None-Match": header}
        )
        assert response.status_code == 304
        assert response.content == b""
        assert response.headers["etag"] == etag

    stale = harness.client.get(
        f"/agents/{uuid4()}/avatar", headers={"If-None-Match": '"stale"'}
    )
    assert stale.status_code == 200


def test_public_get_returns_404_without_an_avatar(harness: Harness) -> None:
    response = harness.client.get(f"/agents/{uuid4()}/avatar")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"
