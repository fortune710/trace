from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest
import sqlalchemy as sa
from avatar_fixtures import make_png
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from agents.avatar import MAX_AVATAR_BYTES
from db.rls import principal_transaction

pytestmark = pytest.mark.integration

CONFIG = {
    "eyes": "variant03",
    "brows": "variant07",
    "nose": "variant04",
    "lips": "variant09",
    "hair": "variant21",
    "body": "variant12",
    "backgroundColor": "#b6e3f4",
    "flip": False,
}


def _avatar_path(agent_id: str) -> str:
    return f"/api/v1/agents/{agent_id}/avatar"


def _upload(account, agent_id: str, png: bytes, config: dict | None = CONFIG):
    return account.request(
        "POST",
        _avatar_path(agent_id),
        files={"file": ("avatar.png", png, "image/png")},
        data={"config": json.dumps(config)} if config is not None else None,
    )


def _anonymous(account) -> TestClient:
    # Reuse the account's TestClient (one event loop, so the shared Redis pool the
    # rate limiter opened is not closed from a second loop) with its cookies
    # dropped. AuthenticatedTestClient restores them on the next authenticated call.
    client = account.client._client
    client.cookies.clear()
    return client


def _public_get(account, agent_id: str, **kwargs):
    return _anonymous(account).get(_avatar_path(agent_id), **kwargs)


def _stored_rows(engine, user_id: UUID | None, agent_id: str) -> int:
    with engine.begin() as connection:
        if user_id is not None:
            connection.execute(
                sa.text("SELECT set_config('trace.current_user_id', :u, true)"),
                {"u": str(user_id)},
            )
        return connection.execute(
            sa.text("SELECT count(*) FROM private.agent_avatars WHERE agent_id = :id"),
            {"id": agent_id},
        ).scalar_one()


def test_owner_uploads_replaces_and_deletes_an_avatar(
    account_pair, agent_factory
) -> None:
    owner, _ = account_pair
    agent_id = agent_factory(owner)["id"]
    first_png = make_png(256)

    uploaded = _upload(owner, agent_id, first_png)

    assert uploaded.status_code == 200, uploaded.text
    digest = hashlib.sha256(first_png).hexdigest()
    body = uploaded.json()
    assert body["avatar"] == f"{_avatar_path(agent_id)}?v={digest[:12]}"
    assert body["avatar_config"] == CONFIG
    assert body["configuration_version"] == 2
    fetched = owner.request("GET", f"/api/v1/agents/{agent_id}").json()
    assert fetched["avatar"] == body["avatar"]
    assert fetched["avatar_config"] == CONFIG
    listed = owner.request("GET", "/api/v1/agents").json()["items"][0]
    assert listed["avatar_config"] == CONFIG

    served = _public_get(owner, agent_id)
    assert served.status_code == 200
    assert served.content == first_png
    assert served.headers["content-type"] == "image/png"
    assert served.headers["etag"] == f'"{digest}"'
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert served.headers["x-content-type-options"] == "nosniff"
    revalidated = _public_get(owner, agent_id, headers={"If-None-Match": f'"{digest}"'})
    assert revalidated.status_code == 304

    second_png = make_png(128)
    replaced = _upload(owner, agent_id, second_png, config=None)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["avatar"] != body["avatar"]
    assert replaced.json()["avatar_config"] is None
    assert replaced.json()["configuration_version"] == 3
    assert _public_get(owner, agent_id).content == second_png

    removed = owner.request("DELETE", _avatar_path(agent_id))
    assert removed.status_code == 204
    after = owner.request("GET", f"/api/v1/agents/{agent_id}").json()
    assert after["avatar"] is None
    assert after["avatar_config"] is None
    assert _public_get(owner, agent_id).status_code == 404
    assert owner.request("DELETE", _avatar_path(agent_id)).status_code == 204


def test_another_owner_cannot_touch_the_avatar_but_the_public_read_works(
    account_pair, agent_factory, integration_engine
) -> None:
    owner, other = account_pair
    agent_id = agent_factory(owner)["id"]
    owner_png = make_png(256)
    assert _upload(owner, agent_id, owner_png).status_code == 200

    foreign_upload = _upload(other, agent_id, make_png(64), config=None)
    foreign_delete = other.request("DELETE", _avatar_path(agent_id))

    for response in (foreign_upload, foreign_delete):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "authorization_denied"
        assert str(owner.user_id) not in response.text
    assert _public_get(owner, agent_id).content == owner_png
    still = owner.request("GET", f"/api/v1/agents/{agent_id}").json()
    assert still["avatar_config"] == CONFIG

    # Row-level security hides the bytes from every direct query that is not the
    # owner's, so only the SECURITY DEFINER function can serve the public read.
    assert _stored_rows(integration_engine, None, agent_id) == 0
    assert _stored_rows(integration_engine, other.user_id, agent_id) == 0
    assert _stored_rows(integration_engine, owner.user_id, agent_id) == 1
    with integration_engine.connect() as connection:
        public = connection.execute(
            sa.text("SELECT sha256 FROM public.read_agent_avatar(:id)"),
            {"id": agent_id},
        ).scalar_one()
    assert public == hashlib.sha256(owner_png).hexdigest()


def test_avatar_endpoints_reject_unknown_agents_and_anonymous_writes(
    account_pair, agent_factory
) -> None:
    owner, _ = account_pair
    agent_id = agent_factory(owner)["id"]
    missing = "0197b3a0-0000-7000-8000-000000000000"

    assert _upload(owner, missing, make_png(64)).status_code == 404
    assert owner.request("DELETE", _avatar_path(missing)).status_code == 404
    assert _public_get(owner, missing).status_code == 404
    assert _public_get(owner, agent_id).status_code == 404

    anonymous = _anonymous(owner)
    upload = anonymous.post(
        _avatar_path(agent_id),
        files={"file": ("avatar.png", make_png(64), "image/png")},
    )
    delete = anonymous.delete(_avatar_path(agent_id))
    assert upload.status_code == 401
    assert delete.status_code == 401


def test_upload_requires_csrf_and_rejects_bad_input_without_changing_the_agent(
    account_pair, agent_factory
) -> None:
    owner, _ = account_pair
    agent_id = agent_factory(owner)["id"]
    good = make_png(64)

    without_csrf = owner.client.request(
        "POST",
        _avatar_path(agent_id),
        files={"file": ("avatar.png", good, "image/png")},
    )
    assert without_csrf.status_code == 403
    assert without_csrf.json()["error"]["code"] == "csrf_validation_failed"
    without_csrf_delete = owner.client.request("DELETE", _avatar_path(agent_id))
    assert without_csrf_delete.status_code == 403

    rejected = {
        "jpeg": (
            owner.request(
                "POST",
                _avatar_path(agent_id),
                files={
                    "file": ("a.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "image/jpeg")
                },
            ),
            415,
        ),
        "not png": (_upload(owner, agent_id, b"plain text, not an image"), 400),
        "not square": (_upload(owner, agent_id, make_png(64, 32)), 400),
        "too big": (_upload(owner, agent_id, make_png(600)), 400),
        "oversized": (
            _upload(owner, agent_id, make_png(16, pad=MAX_AVATAR_BYTES)),
            413,
        ),
        "bad config key": (
            _upload(owner, agent_id, good, {**CONFIG, "gesture": "variant01"}),
            400,
        ),
        "bad config value": (
            _upload(owner, agent_id, good, {**CONFIG, "eyes": "variant06"}),
            400,
        ),
    }
    for label, (response, expected) in rejected.items():
        assert response.status_code == expected, label
        assert response.json()["error"]["code"] == "invalid_request", label
    malformed = owner.request(
        "POST",
        _avatar_path(agent_id),
        files={"file": ("avatar.png", good, "image/png")},
        data={"config": "{broken"},
    )
    assert malformed.status_code == 400

    unchanged = owner.request("GET", f"/api/v1/agents/{agent_id}").json()
    assert unchanged["avatar"] is None
    assert unchanged["avatar_config"] is None
    assert unchanged["configuration_version"] == 1


def test_patching_avatar_to_a_new_value_clears_the_stored_avatar(
    account_pair, agent_factory
) -> None:
    owner, _ = account_pair
    agent_id = agent_factory(owner)["id"]
    uploaded = _upload(owner, agent_id, make_png(256)).json()

    same = owner.request(
        "PATCH",
        f"/api/v1/agents/{agent_id}",
        json={"avatar": uploaded["avatar"], "name": "renamed"},
    )
    assert same.status_code == 200
    assert same.json()["avatar_config"] == CONFIG
    assert _public_get(owner, agent_id).status_code == 200

    unrelated = owner.request(
        "PATCH", f"/api/v1/agents/{agent_id}", json={"name": "again"}
    )
    assert unrelated.json()["avatar_config"] == CONFIG

    changed = owner.request(
        "PATCH",
        f"/api/v1/agents/{agent_id}",
        json={"avatar": "https://cdn.example.test/other.png"},
    )
    assert changed.status_code == 200
    assert changed.json()["avatar"] == "https://cdn.example.test/other.png"
    assert changed.json()["avatar_config"] is None
    assert _public_get(owner, agent_id).status_code == 404

    # AgentUpdate does not accept the config directly.
    forbidden = owner.request(
        "PATCH",
        f"/api/v1/agents/{agent_id}",
        json={"avatar_config": CONFIG},
    )
    assert forbidden.status_code == 400


def test_database_rejects_a_non_object_avatar_config(
    account_pair, agent_factory, integration_engine
) -> None:
    owner, _ = account_pair
    agent_id = agent_factory(owner)["id"]

    for payload in ("[]", '"text"', "null", json.dumps({"k": "x" * 1100})):
        with (
            pytest.raises(IntegrityError),
            principal_transaction(integration_engine, owner.user_id) as connection,
        ):
            connection.execute(
                sa.text(
                    "UPDATE public.agents SET avatar_config = CAST(:v AS jsonb) "
                    "WHERE id = :id"
                ),
                {"v": payload, "id": agent_id},
            )


def test_avatar_rows_cascade_with_their_agent(
    account_pair, agent_factory, integration_engine
) -> None:
    owner, _ = account_pair
    agent_id = agent_factory(owner)["id"]
    assert _upload(owner, agent_id, make_png(64)).status_code == 200
    assert _stored_rows(integration_engine, owner.user_id, agent_id) == 1

    with principal_transaction(integration_engine, owner.user_id) as connection:
        connection.execute(
            sa.text("DELETE FROM public.agents WHERE id = :id"), {"id": agent_id}
        )
    with integration_engine.connect() as connection:
        remaining = connection.execute(
            sa.text("SELECT count(*) FROM public.read_agent_avatar(:id)"),
            {"id": agent_id},
        ).scalar_one()
    assert remaining == 0
