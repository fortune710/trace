from __future__ import annotations

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa

from auth.credential_service import CredentialService
from auth.credentials import CredentialCipher
from auth.errors import AuthorizationDenied
from auth.models import AuthUser, UserStatus
from credentials.models import (
    Credential,
    CredentialKind,
    CredentialProvider,
)
from db.rls import principal_transaction
from users.models import User


@pytest.mark.integration
def test_credential_service_encrypts_and_scopes_records() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    engine = sa.create_engine(database_url)
    owner_id = uuid4()
    other_owner_id = uuid4()
    payload = {"access_token": "github-secret-access-token"}

    try:
        with engine.begin() as connection:
            for user_id, email in (
                (owner_id, f"credential-owner-{owner_id}@example.test"),
                (other_owner_id, f"credential-other-{other_owner_id}@example.test"),
            ):
                connection.execute(
                    sa.insert(AuthUser).values(
                        id=user_id,
                        email=email,
                        status=UserStatus.ACTIVE,
                    )
                )
                connection.execute(sa.insert(User).values(id=user_id))

        service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
        )
        metadata = service.create_or_replace(
            owner_id=owner_id,
            provider=CredentialProvider.GITHUB,
            kind=CredentialKind.OAUTH,
            payload=payload,
        )

        with principal_transaction(engine, owner_id) as connection:
            row = connection.execute(
                sa.select(Credential.ciphertext).where(Credential.id == metadata.id)
            ).scalar_one()
        assert b"github-secret-access-token" not in row
        assert (
            service.decrypt_for_provider_call(
                owner_id=owner_id, credential_id=metadata.id
            )
            == payload
        )
        with pytest.raises(AuthorizationDenied):
            service.decrypt_for_provider_call(
                owner_id=other_owner_id, credential_id=metadata.id
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                sa.delete(AuthUser).where(AuthUser.id.in_([owner_id, other_owner_id]))
            )
        engine.dispose()
