from __future__ import annotations

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa

from auth.credential_service import CredentialService
from auth.credentials import CredentialCipher
from auth.models import AuthUser, UserStatus
from credentials.models import (
    Credential,
    CredentialEncryptionProvider,
    CredentialKind,
    CredentialProvider,
    CredentialReencryptionRun,
)
from db.rls import principal_transaction
from maintenance.credential_rotation import CredentialRotationJob
from users.models import User


@pytest.mark.integration
def test_credential_rotation_rewraps_existing_ciphertext_and_is_resumable() -> None:
    database_url = os.environ.get("DATABASE_URL")
    maintenance_database_url = os.environ.get("MAINTENANCE_DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    assert maintenance_database_url and "postgres-test" in maintenance_database_url
    engine = sa.create_engine(database_url)
    maintenance_engine = sa.create_engine(maintenance_database_url)
    owner_id = uuid4()
    run_id = None

    try:
        with engine.begin() as connection:
            connection.execute(
                sa.insert(AuthUser).values(
                    id=owner_id,
                    email=f"rotation-owner-{owner_id}@example.test",
                    status=UserStatus.ACTIVE,
                )
            )
            connection.execute(sa.insert(User).values(id=owner_id))

        old_service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"a" * 32, key_version="local-v1"),
        )
        metadata = old_service.create_or_replace(
            owner_id=owner_id,
            provider=CredentialProvider.GITHUB,
            kind=CredentialKind.OAUTH,
            payload={"access_token": "rotation-secret"},
        )
        new_cipher = CredentialCipher(
            key=b"b" * 32,
            key_version="local-v2",
            verification_keys={"local-v1": b"a" * 32},
        )
        job = CredentialRotationJob(
            engine=maintenance_engine,
            cipher=new_cipher,
            encryption_provider=CredentialEncryptionProvider.LOCAL,
            target_key_reference="local-v2",
            target_key_version="local-v2",
            batch_size=1,
        )

        result = job.run()
        run_id = result.run_id
        assert result.status.value == "completed"
        assert result.rewrapped_count == 1
        assert result.failed_count == 0

        with principal_transaction(engine, owner_id) as connection:
            assert (
                connection.execute(
                    sa.select(Credential.key_version).where(
                        Credential.id == metadata.id
                    )
                ).scalar_one()
                == "local-v2"
            )

        resumed = job.run(run_id=result.run_id)
        assert resumed.status.value == "completed"
        assert resumed.rewrapped_count == 1
    finally:
        with maintenance_engine.begin() as connection:
            if run_id is not None:
                connection.execute(
                    sa.delete(CredentialReencryptionRun).where(
                        CredentialReencryptionRun.id == run_id
                    )
                )
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        maintenance_engine.dispose()
        engine.dispose()


@pytest.mark.integration
def test_provider_read_repairs_a_retired_local_key_version() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    engine = sa.create_engine(database_url)
    owner_id = uuid4()

    try:
        with engine.begin() as connection:
            connection.execute(
                sa.insert(AuthUser).values(
                    id=owner_id,
                    email=f"read-repair-owner-{owner_id}@example.test",
                    status=UserStatus.ACTIVE,
                )
            )
            connection.execute(sa.insert(User).values(id=owner_id))

        old_service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(key=b"d" * 32, key_version="local-v1"),
        )
        metadata = old_service.create_or_replace(
            owner_id=owner_id,
            provider=CredentialProvider.OPENAI,
            kind=CredentialKind.API_KEY,
            payload={"api_key": "read-repair-secret"},
        )
        new_service = CredentialService(
            engine=engine,
            cipher=CredentialCipher(
                key=b"e" * 32,
                key_version="local-v2",
                verification_keys={"local-v1": b"d" * 32},
            ),
        )

        assert new_service.decrypt_for_provider_call(
            owner_id=owner_id, credential_id=metadata.id
        ) == {"api_key": "read-repair-secret"}
        with principal_transaction(engine, owner_id) as connection:
            assert (
                connection.execute(
                    sa.select(Credential.key_version).where(
                        Credential.id == metadata.id
                    )
                ).scalar_one()
                == "local-v2"
            )
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.id == owner_id))
        engine.dispose()
