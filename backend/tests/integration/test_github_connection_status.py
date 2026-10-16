from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from auth.oauth import OAuthRejected, OAuthUnavailable

pytestmark = pytest.mark.integration


def _credential(account, *, expires_at: datetime | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"access_token": "github-access-token"}
    if expires_at is not None:
        payload["access_token_expires_at"] = expires_at.isoformat()
    response = account.request(
        "POST",
        "/api/v1/credentials",
        json={"provider": "github", "kind": "oauth", "payload": payload},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_github_connection_status_requires_authentication(integration_app) -> None:
    with TestClient(integration_app) as client:
        response = client.get("/auth/oauth/github/connection")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_github_connection_status_is_owner_scoped_and_uses_the_enum(
    account_pair, credential_factory, external_repository_factory, integration_app
) -> None:
    owner, other = account_pair
    credential = credential_factory(owner)
    external_repository_factory(owner, credential["id"])

    owner_response = owner.request("GET", "/auth/oauth/github/connection")
    other_response = other.request("GET", "/auth/oauth/github/connection")
    schema = integration_app.openapi()["paths"]["/auth/oauth/github/connection"][
        "get"
    ]["responses"]["200"]["content"]["application/json"]["schema"]

    assert owner_response.status_code == 200, owner_response.text
    assert owner_response.json() == {"provider": "github", "status": "connected"}
    assert other_response.status_code == 200, other_response.text
    assert other_response.json() == {
        "provider": "github",
        "status": "never_connected",
    }
    assert schema["$ref"].endswith("GitHubConnectionStatusResponse")


def test_github_connection_status_accepts_missing_or_future_expiry_without_refresh(
    account_pair, external_repository_factory, monkeypatch
) -> None:
    owner, _ = account_pair
    no_expiry = _credential(owner)
    external_repository_factory(owner, no_expiry["id"])
    monkeypatch.setattr(
        "auth.oauth.refresh_github_credential",
        lambda **_kwargs: pytest.fail("a valid token must not be refreshed"),
    )

    response = owner.request("GET", "/auth/oauth/github/connection")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "connected"

    future = owner.request(
        "POST",
        "/api/v1/credentials",
        json={
            "provider": "github",
            "kind": "oauth",
            "payload": {
                "access_token": "github-access-token",
                "access_token_expires_at": (
                    datetime.now(UTC) + timedelta(minutes=5)
                ).isoformat(),
            },
        },
    )
    assert future.status_code == 201, future.text
    future_response = owner.request("GET", "/auth/oauth/github/connection")

    assert future_response.status_code == 200, future_response.text
    assert future_response.json()["status"] == "connected"


def test_github_connection_status_refreshes_an_expired_token(
    account_pair, external_repository_factory, monkeypatch
) -> None:
    owner, _ = account_pair
    credential = _credential(owner, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    external_repository_factory(owner, credential["id"])
    refresh_calls: list[dict[str, object]] = []

    def refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {"access_token": "refreshed-token"}

    monkeypatch.setattr("auth.oauth.refresh_github_credential", refresh)

    response = owner.request("GET", "/auth/oauth/github/connection")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "connected"
    assert refresh_calls and refresh_calls[0]["owner_id"] == owner.user_id


def test_github_connection_status_requires_reconnection_after_rejected_refresh(
    account_pair, external_repository_factory, monkeypatch
) -> None:
    owner, _ = account_pair
    credential = _credential(owner, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    external_repository_factory(owner, credential["id"])

    def reject_refresh(**_kwargs):
        raise OAuthRejected("expired credential")

    monkeypatch.setattr("auth.oauth.refresh_github_credential", reject_refresh)

    response = owner.request("GET", "/auth/oauth/github/connection")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "needs_reconnection"


def test_github_connection_status_surfaces_temporary_refresh_outages_safely(
    account_pair, external_repository_factory, monkeypatch
) -> None:
    owner, _ = account_pair
    credential = _credential(owner, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    external_repository_factory(owner, credential["id"])

    def unavailable_refresh(**_kwargs):
        raise OAuthUnavailable("provider unavailable")

    monkeypatch.setattr("auth.oauth.refresh_github_credential", unavailable_refresh)

    response = owner.request("GET", "/auth/oauth/github/connection")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_temporarily_unavailable"
