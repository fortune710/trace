from __future__ import annotations

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa

from db.models import AuthUser, Project, ProjectSourceType, User, UserStatus
from db.rls import principal_transaction


@pytest.mark.integration
def test_owner_rls_isolation_and_transaction_local_context() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url and "postgres-test" in database_url
    engine = sa.create_engine(database_url)
    owner_id = uuid4()
    other_owner_id = uuid4()
    owner_project_id = uuid4()
    other_project_id = uuid4()

    try:
        with engine.begin() as connection:
            for user_id, email in (
                (owner_id, f"rls-owner-{owner_id}@example.test"),
                (other_owner_id, f"rls-other-{other_owner_id}@example.test"),
            ):
                connection.execute(
                    sa.insert(AuthUser).values(
                        id=user_id,
                        email=email,
                        status=UserStatus.ACTIVE,
                    )
                )
                connection.execute(sa.insert(User).values(id=user_id))

        with principal_transaction(engine, owner_id) as connection:
            connection.execute(
                sa.insert(Project).values(
                    id=owner_project_id,
                    owner_id=owner_id,
                    name="owner project",
                    source_type=ProjectSourceType.LOCAL,
                    local_path_hash=b"owner-path",
                )
            )
            assert connection.execute(
                sa.text("SELECT current_setting('trace.current_user_id', true)")
            ).scalar_one() == str(owner_id)

        with principal_transaction(engine, other_owner_id) as connection:
            connection.execute(
                sa.insert(Project).values(
                    id=other_project_id,
                    owner_id=other_owner_id,
                    name="other project",
                    source_type=ProjectSourceType.LOCAL,
                    local_path_hash=b"other-path",
                )
            )

        with engine.connect() as connection:
            assert connection.execute(
                sa.text("SELECT current_setting('trace.current_user_id', true)")
            ).scalar_one_or_none() in {"", None}
            assert connection.execute(sa.select(Project)).scalars().all() == []

        with principal_transaction(engine, owner_id) as connection:
            visible_ids = set(connection.execute(sa.select(Project.id)).scalars())
            assert visible_ids == {owner_project_id}

            connection.execute(
                sa.update(Project)
                .where(Project.id == other_project_id)
                .values(name="must not change")
            )
            assert (
                connection.execute(
                    sa.select(Project.name).where(Project.id == other_project_id)
                ).scalar_one_or_none()
                is None
            )

            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(
                    sa.insert(Project).values(
                        id=uuid4(),
                        owner_id=other_owner_id,
                        name="cross-account insert",
                        source_type=ProjectSourceType.LOCAL,
                        local_path_hash=b"cross-account-path",
                    )
                )

        with engine.connect() as connection:
            roles = dict(
                connection.execute(
                    sa.text(
                        "SELECT rolname, rolbypassrls "
                        "FROM pg_roles WHERE rolname IN ('trace_app', 'trace_internal')"
                    )
                ).all()
            )
            assert roles["trace_app"] is False
            assert roles["trace_internal"] is True
            rls_state = connection.execute(
                sa.text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class "
                    "WHERE oid = 'public.projects'::regclass"
                )
            ).one()
            assert rls_state == (True, True)
    finally:
        with engine.begin() as connection:
            connection.execute(
                sa.delete(AuthUser).where(AuthUser.id.in_([owner_id, other_owner_id]))
            )
        engine.dispose()


@pytest.mark.integration
def test_internal_worker_role_is_limited_to_email_jobs() -> None:
    internal_database_url = os.environ.get("INTERNAL_DATABASE_URL")
    assert internal_database_url and "postgres-test" in internal_database_url
    engine = sa.create_engine(internal_database_url)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    sa.text("SELECT count(*) FROM auth.email_delivery_jobs")
                ).scalar_one()
                == 0
            )
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text("SELECT count(*) FROM public.projects"))
    finally:
        engine.dispose()
