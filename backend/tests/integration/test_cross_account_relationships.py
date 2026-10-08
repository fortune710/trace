from __future__ import annotations

import time
from uuid import UUID

import jwt
import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from auth.models import AuthSession
from db.rls import principal_transaction
from remediations.models import Remediation
from reviews.models import ReviewRunAgent

pytestmark = pytest.mark.integration


def test_cross_account_relationships_are_rejected_without_side_effects(
    account_pair,
    credential_factory,
    external_repository_factory,
    local_project_factory,
    agent_factory,
    artifact_graph_factory,
    integration_engine,
) -> None:
    owner, other = account_pair

    foreign_credential = credential_factory(other)
    foreign_connection = external_repository_factory(
        other, UUID(foreign_credential["id"])
    )
    foreign_project = local_project_factory(other, name="foreign-project")
    foreign_agent = agent_factory(other, name="foreign-agent")
    owner_project = local_project_factory(owner, name="owner-project")

    project_attempt = owner.request(
        "POST",
        "/api/v1/projects",
        json={
            "name": "cross-account-github",
            "source": "github",
            "external_repository_id": "foreign-repo",
            "external_repository_connection_id": str(foreign_connection),
        },
    )
    assert project_attempt.status_code == 403
    assert str(foreign_connection) not in project_attempt.text

    agent_attempt = owner.request(
        "POST",
        "/api/v1/agents",
        json={
            "name": "cross-account-agent",
            "review_category": "security",
            "model_provider": "github",
            "model_name": "integration-model",
            "credential_id": foreign_credential["id"],
        },
    )
    assert agent_attempt.status_code == 403
    assert foreign_credential["id"] not in agent_attempt.text

    review_attempt = owner.request(
        "POST",
        "/api/v1/reviews",
        json={
            "project_id": foreign_project["id"],
            "source_revision": "cross-account",
            "selected_categories": ["security"],
            "agent_ids": [foreign_agent["id"]],
        },
    )
    assert review_attempt.status_code == 403
    assert foreign_project["id"] not in review_attempt.text
    assert foreign_agent["id"] not in review_attempt.text

    owner_agent = agent_factory(owner)
    graph = artifact_graph_factory(other, foreign_project["id"], foreign_agent["id"])
    before = other.request("GET", "/api/v1/findings/" + str(graph["finding_id"]))
    assert before.status_code == 200
    remediation_count_before = len(
        other.request(
            "GET", f"/api/v1/findings/{graph['finding_id']}/remediations"
        ).json()
    )
    remediation_attempt = owner.request(
        "POST",
        f"/api/v1/findings/{graph['finding_id']}/remediations",
        json={"proposed_diff": "cross-account"},
    )
    assert remediation_attempt.status_code == 403
    assert (
        len(
            other.request(
                "GET", f"/api/v1/findings/{graph['finding_id']}/remediations"
            ).json()
        )
        == remediation_count_before
    )

    owner_graph = artifact_graph_factory(owner, owner_project["id"], owner_agent["id"])
    for path in (
        f"/api/v1/pull-requests/{graph['pull_request_id']}",
        f"/api/v1/local-file-backups/{graph['backup_id']}",
    ):
        response = owner.request("GET", path)
        assert response.status_code == 403
        assert str(graph["remediation_id"]) not in response.text
    assert str(owner_graph["finding_id"]) not in before.text


def test_same_owner_composite_foreign_keys_block_direct_relationship_inserts(
    account_pair,
    local_project_factory,
    agent_factory,
    review_factory,
    integration_engine,
) -> None:
    owner, other = account_pair
    owner_project = local_project_factory(owner)
    owner_agent = agent_factory(owner)
    foreign_agent = agent_factory(other)
    review = review_factory(owner, owner_project["id"], [owner_agent["id"]])

    with (
        pytest.raises(sa.exc.DBAPIError),
        principal_transaction(integration_engine, owner.user_id) as connection,
    ):
        connection.execute(
            sa.insert(ReviewRunAgent).values(
                owner_id=owner.user_id,
                review_run_id=UUID(review["id"]),
                agent_id=UUID(foreign_agent["id"]),
            )
        )

    with (
        pytest.raises(sa.exc.DBAPIError),
        principal_transaction(integration_engine, owner.user_id) as connection,
    ):
        connection.execute(
            sa.insert(Remediation).values(
                id=UUID(review["id"]),
                owner_id=owner.user_id,
                project_id=UUID(foreign_agent["id"]),
                finding_id=UUID(review["id"]),
                proposed_diff="invalid relationship",
            )
        )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/projects",
        "/api/v1/agents",
        "/api/v1/reviews",
        "/api/v1/findings/00000000-0000-0000-0000-000000000001",
        "/api/v1/remediations/00000000-0000-0000-0000-000000000001",
        "/api/v1/credentials",
        "/api/v1/pull-requests/00000000-0000-0000-0000-000000000001",
    ],
)
def test_protected_collections_reject_missing_and_malformed_access_cookies(
    path: str,
    integration_app,
) -> None:
    missing = TestClient(integration_app).get(path)
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "authentication_required"

    malformed_client = TestClient(integration_app)
    malformed_client.cookies.set("__Host-trace_access", "not-a-jwt")
    malformed = malformed_client.get(path)
    assert malformed.status_code == 401
    assert malformed.json()["error"]["code"] == "authentication_required"
    malformed_client.close()


def test_revoked_session_is_rejected_across_protected_routes(
    account_pair,
    integration_engine,
) -> None:
    owner, _ = account_pair
    with integration_engine.begin() as connection:
        connection.execute(
            sa.update(AuthSession)
            .where(AuthSession.id == owner.session_id)
            .values(revoked_at=sa.func.current_timestamp())
        )

    for path in (
        "/api/v1/projects",
        "/api/v1/agents",
        "/api/v1/reviews",
        "/api/v1/credentials",
    ):
        response = owner.request("GET", path)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.parametrize("token_kind", ["expired", "wrong_audience", "wrong_signature"])
def test_invalid_access_token_variants_are_generic(
    token_kind: str,
    integration_app,
    integration_settings,
) -> None:
    now = int(time.time())
    payload = {
        "iss": integration_settings.jwt_issuer,
        "aud": integration_settings.jwt_audience,
        "sub": str(UUID("00000000-0000-0000-0000-000000000001")),
        "sid": str(UUID("00000000-0000-0000-0000-000000000002")),
        "jti": "integration-invalid-token",
        "iat": now - 60,
        "nbf": now - 60,
        "exp": now + 60,
        "token_use": "access",
    }
    if token_kind == "expired":
        payload["exp"] = now - 1
    elif token_kind == "wrong_audience":
        payload["aud"] = "wrong-audience"
    signing_key = Ed25519PrivateKey.from_private_bytes(
        b"z" * 32 if token_kind == "wrong_signature" else b"a" * 32
    )
    token = jwt.encode(
        payload,
        signing_key,
        algorithm="EdDSA",
        headers={"kid": "local-v1", "typ": "at+jwt"},
    )
    client = TestClient(integration_app)
    client.cookies.set(integration_settings.access_cookie_name, token)
    try:
        response = client.get("/api/v1/projects")
    finally:
        client.close()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "POST",
            "/api/v1/projects",
            {"name": "csrf", "source": "local", "local_path_hash": "a" * 64},
        ),
        (
            "POST",
            "/api/v1/agents",
            {
                "name": "csrf",
                "review_category": "security",
                "model_provider": "trace",
                "model_name": "model",
            },
        ),
        (
            "POST",
            "/api/v1/reviews",
            {
                "project_id": str(UUID(int=1)),
                "source_revision": "csrf",
                "selected_categories": ["security"],
                "agent_ids": [],
            },
        ),
        (
            "PATCH",
            "/api/v1/findings/00000000-0000-0000-0000-000000000001",
            {"status": "accepted"},
        ),
        (
            "POST",
            "/api/v1/findings/00000000-0000-0000-0000-000000000001/remediations",
            {"proposed_diff": "csrf"},
        ),
        (
            "POST",
            "/api/v1/remediations/00000000-0000-0000-0000-000000000001/approve",
            None,
        ),
        (
            "POST",
            "/api/v1/credentials",
            {
                "provider": "github",
                "kind": "oauth",
                "payload": {"access_token": "csrf"},
            },
        ),
    ],
)
def test_unsafe_resource_routes_require_csrf(
    method: str,
    path: str,
    body: dict[str, object] | None,
    account_pair,
) -> None:
    owner, _ = account_pair
    response = owner.client.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_validation_failed"
