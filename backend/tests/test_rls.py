from __future__ import annotations

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa

from auth.models import AuthUser, UserStatus
from db.rls import principal_transaction
from db.types import ProjectSourceType
from projects.models import Project
from users.models import User


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
                    source=ProjectSourceType.LOCAL,
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
                    source=ProjectSourceType.LOCAL,
                    local_path_hash=b"other-path",
                )
            )

        with engine.connect() as connection:
            assert connection.execute(
                sa.text("SELECT current_setting('trace.current_user_id', true)")
            ).scalar_one_or_none() in {"", None}
            assert connection.execute(sa.select(Project)).scalars().all() == []
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(
                    sa.text(
                        "SELECT count(*) FROM private.remediation_pull_request_outbox_jobs"
                    )
                )

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
                        source=ProjectSourceType.LOCAL,
                        local_path_hash=b"cross-account-path",
                    )
                )

        with engine.connect() as connection:
            roles: dict[object, object] = dict(
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
def test_internal_worker_role_has_only_the_access_required_by_internal_workers() -> (
    None
):
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
            assert (
                connection.execute(
                    sa.text("SELECT count(*) FROM public.reviews")
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    sa.text("SELECT count(*) FROM private.review_dispatch_jobs")
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    sa.text(
                        "SELECT count(*) FROM private.remediation_pull_request_outbox_jobs"
                    )
                ).scalar_one()
                == 0
            )
            required_privileges = {
                "public.reviews": {"SELECT", "UPDATE"},
                "public.review_agents": {"SELECT", "UPDATE"},
                "public.findings": {"INSERT"},
                "public.external_repositories": {"SELECT"},
                "private.review_dispatch_jobs": {"SELECT", "UPDATE", "DELETE"},
                "private.remediation_pull_request_outbox_jobs": {
                    "SELECT",
                    "UPDATE",
                    "DELETE",
                },
                "private.credentials": {"SELECT", "UPDATE"},
                "private.review_agent_attempts": {"SELECT", "INSERT", "UPDATE"},
                "private.review_agent_execution_configs": {"SELECT"},
            }
            for relation, privileges in required_privileges.items():
                for privilege in privileges:
                    assert connection.execute(
                        sa.text(
                            "SELECT has_table_privilege("
                            "current_user, :relation, :privilege)"
                        ),
                        {"relation": relation, "privilege": privilege},
                    ).scalar_one()
            for column in ("owner_id", "review_id", "agent_id", "content_digest"):
                assert connection.execute(
                    sa.text(
                        "SELECT has_column_privilege("
                        "current_user, 'public.findings', :column, 'SELECT')"
                    ),
                    {"column": column},
                ).scalar_one()
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text("SELECT count(*) FROM public.projects"))
    finally:
        engine.dispose()


@pytest.mark.integration
def test_review_and_remediation_workers_have_persistence_access() -> None:
    internal_database_url = os.environ.get("INTERNAL_DATABASE_URL")
    assert internal_database_url and "postgres-test" in internal_database_url
    engine = sa.create_engine(internal_database_url)
    try:
        with engine.connect() as connection:
            for relation, column, privilege in (
                ("public.users", "id", "SELECT"),
                ("public.users", "automatic_pull_requests", "SELECT"),
                ("public.projects", "id", "SELECT"),
                ("public.projects", "owner_id", "SELECT"),
                ("public.projects", "source", "SELECT"),
                ("public.projects", "external_repository_id", "SELECT"),
                ("public.projects", "branch_name", "SELECT"),
                ("public.findings", "id", "SELECT"),
                ("public.findings", "status", "SELECT"),
                ("public.findings", "title", "SELECT"),
                ("public.remediations", "id", "INSERT"),
                ("public.remediations", "owner_id", "INSERT"),
                ("public.remediations", "project_id", "INSERT"),
                ("public.remediations", "finding_id", "INSERT"),
                ("public.remediations", "prompt_text", "INSERT"),
                ("public.remediations", "proposed_diff", "INSERT"),
                ("public.remediations", "status", "INSERT"),
                (
                    "private.remediation_pull_request_outbox_jobs",
                    "idempotency_id",
                    "INSERT",
                ),
                (
                    "private.remediation_pull_request_outbox_jobs",
                    "owner_id",
                    "INSERT",
                ),
                (
                    "private.remediation_pull_request_outbox_jobs",
                    "remediation_id",
                    "INSERT",
                ),
                (
                    "private.remediation_pull_request_jobs",
                    "id",
                    "INSERT",
                ),
                (
                    "private.remediation_pull_request_jobs",
                    "id",
                    "SELECT",
                ),
                (
                    "private.remediation_pull_request_jobs",
                    "owner_id",
                    "SELECT",
                ),
                (
                    "private.remediation_pull_request_jobs",
                    "remediation_id",
                    "SELECT",
                ),
                ("private.audit_delivery_jobs", "event_id", "INSERT"),
                ("private.audit_delivery_jobs", "owner_id", "INSERT"),
                ("private.audit_delivery_jobs", "canonical_json", "INSERT"),
                ("private.audit_delivery_jobs", "event_hash", "INSERT"),
                ("private.audit_delivery_jobs", "status", "INSERT"),
            ):
                assert connection.execute(
                    sa.text(
                        "SELECT has_column_privilege("
                        "current_user, :relation, :column, :privilege)"
                    ),
                    {
                        "relation": relation,
                        "column": column,
                        "privilege": privilege,
                    },
                ).scalar_one()
    finally:
        engine.dispose()
