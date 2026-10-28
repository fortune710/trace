from contextlib import contextmanager
from typing import cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from auth.errors import ResourceUnavailable
from resources.services import ArtifactService


def test_remediation_prompt_maps_database_outages_to_safe_unavailable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def unavailable_transaction(*_args: object, **_kwargs: object):
        raise sa.exc.OperationalError("SELECT 1", {}, RuntimeError("database offline"))
        yield

    monkeypatch.setattr(
        "resources.services.principal_transaction", unavailable_transaction
    )

    with pytest.raises(ResourceUnavailable) as error:
        ArtifactService(cast(Engine, object())).get_remediation_prompt(
            owner_id=uuid4(), remediation_id=uuid4()
        )

    assert error.value.code == "resource_unavailable"
