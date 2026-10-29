from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


def test_ensuring_a_local_project_handle_is_idempotent(account_pair) -> None:
    owner, _ = account_pair
    client_project_id = uuid4()
    body = {"client_project_id": str(client_project_id)}

    first = owner.request("POST", "/api/v1/local-project-handles", json=body)
    second = owner.request("POST", "/api/v1/local-project-handles", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["client_project_id"] == str(client_project_id)
