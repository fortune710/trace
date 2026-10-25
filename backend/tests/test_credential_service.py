from __future__ import annotations

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa

from auth.credential_service import (
    CredentialConflict,
    CredentialPayloadError,
    CredentialService,
)
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


def _seed_owner(engine, owner_id) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(AuthUser).values(
                id=owner_id,
                email=f"credential-named-{owner_id}@example.test",
                status=UserStatus.ACTIVE,
            )
        )
        connection.execute(sa.insert(User).values(id=owner_id))


@pytest.mark.integration
def test_create_named_allows_multiple_active_keys_per_provider() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    engine = sa.create_engine(database_url)
    owner_id = uuid4()
    try:
        _seed_owner(engine, owner_id)
        service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
        )
        first = service.create_named(
            owner_id=owner_id,
            provider=CredentialProvider.OPENAI,
            kind=CredentialKind.API_KEY,
            name="Primary",
            payload={"api_key": "sk-first"},
        )
        second = service.create_named(
            owner_id=owner_id,
            provider=CredentialProvider.OPENAI,
            kind=CredentialKind.API_KEY,
            name="Secondary",
            payload={"api_key": "sk-second"},
        )
        assert first.id != second.id
        assert first.name == "Primary"
        assert second.name == "Secondary"
        assert service.decrypt_for_provider_call(
            owner_id=owner_id, credential_id=first.id
        ) == {"api_key": "sk-first"}
        items, next_offset = service.list_metadata(owner_id=owner_id)
        assert {"Primary", "Secondary"} <= {item.name for item in items}
        assert next_offset is None
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()


@pytest.mark.integration
def test_create_named_rejects_duplicate_active_name_but_reuses_revoked() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    engine = sa.create_engine(database_url)
    owner_id = uuid4()
    try:
        _seed_owner(engine, owner_id)
        service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
        )
        first = service.create_named(
            owner_id=owner_id,
            provider=CredentialProvider.OPENAI,
            kind=CredentialKind.API_KEY,
            name="Primary",
            payload={"api_key": "sk-first"},
        )
        # Names are unique per owner, regardless of provider.
        with pytest.raises(CredentialConflict):
            service.create_named(
                owner_id=owner_id,
                provider=CredentialProvider.ANTHROPIC,
                kind=CredentialKind.API_KEY,
                name="Primary",
                payload={"api_key": "sk-other-provider"},
            )
        service.revoke(owner_id=owner_id, credential_id=first.id)
        reused = service.create_named(
            owner_id=owner_id,
            provider=CredentialProvider.OPENAI,
            kind=CredentialKind.API_KEY,
            name="Primary",
            payload={"api_key": "sk-replacement"},
        )
        assert reused.id != first.id
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()


@pytest.mark.integration
def test_create_named_rejects_invalid_names() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    engine = sa.create_engine(database_url)
    owner_id = uuid4()
    try:
        _seed_owner(engine, owner_id)
        service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
        )
        for bad_name in ("", "   ", "x" * 101):
            with pytest.raises(CredentialPayloadError):
                service.create_named(
                    owner_id=owner_id,
                    provider=CredentialProvider.OPENAI,
                    kind=CredentialKind.API_KEY,
                    name=bad_name,
                    payload={"api_key": "sk-test"},
                )
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()


@pytest.mark.integration
def test_create_or_replace_unnamed_still_replaces() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    engine = sa.create_engine(database_url)
    owner_id = uuid4()
    try:
        _seed_owner(engine, owner_id)
        service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"c" * 32, key_version="test-v1"),
        )
        named = service.create_named(
            owner_id=owner_id,
            provider=CredentialProvider.OPENAI,
            kind=CredentialKind.API_KEY,
            name="Named key",
            payload={"api_key": "sk-named"},
        )
        first = service.create_or_replace(
            owner_id=owner_id,
            provider=CredentialProvider.OPENAI,
            kind=CredentialKind.API_KEY,
            payload={"api_key": "sk-one"},
        )
        second = service.create_or_replace(
            owner_id=owner_id,
            provider=CredentialProvider.OPENAI,
            kind=CredentialKind.API_KEY,
            payload={"api_key": "sk-two"},
        )
        assert first.id == second.id
        assert first.name is None
        assert second.id != named.id
        assert service.decrypt_for_provider_call(
            owner_id=owner_id, credential_id=second.id
        ) == {"api_key": "sk-two"}
        assert service.decrypt_for_provider_call(
            owner_id=owner_id, credential_id=named.id
        ) == {"api_key": "sk-named"}
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
