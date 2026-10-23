import sqlalchemy as sa

from agents.models import Agent
from artifacts.models import LocalFileBackup, PullRequest
from audit.models import AuditDeliveryJob
from auth.models import (
    AuthIdentity,
    AuthSession,
    AuthUser,
    EmailDeliveryJob,
    EmailVerificationToken,
    PasswordRecoveryToken,
    RefreshToken,
)
from credentials.models import Credential
from db.base import Base
from external_repositories.models import ExternalRepository
from findings.models import Finding
from projects.models import Project
from remediations.models import Remediation
from reviews.models import ReviewRun


def test_string_columns_use_text_and_provider_fields_use_native_enums() -> None:
    assert isinstance(AuthUser.__table__.c.email.type, sa.Text)
    assert isinstance(AuthIdentity.__table__.c.provider_subject.type, sa.Text)
    assert isinstance(Project.__table__.c.name.type, sa.Text)
    assert isinstance(Credential.__table__.c.key_version.type, sa.Text)
    assert isinstance(Credential.__table__.c.key_reference.type, sa.Text)
    assert isinstance(Credential.__table__.c.mutation_version.type, sa.Integer)
    assert isinstance(ReviewRun.__table__.c.retry_version.type, sa.Integer)
    assert isinstance(Remediation.__table__.c.mutation_version.type, sa.Integer)
    assert isinstance(EmailDeliveryJob.__table__.c.payload_key_version.type, sa.Text)
    assert isinstance(EmailDeliveryJob.__table__.c.payload_key_reference.type, sa.Text)
    assert isinstance(Credential.__table__.c.encryption_provider.type, sa.Enum)
    assert isinstance(AuthIdentity.__table__.c.provider.type, sa.Enum)
    assert isinstance(Project.__table__.c.source.type, sa.Enum)
    assert AuthIdentity.__table__.c.provider.type.native_enum
    assert Project.__table__.c.source.type.native_enum


def test_all_auth_and_public_tables_match_the_database_contract() -> None:
    expected_tables = {
        "auth": {
            "email_verification_tokens",
            "email_delivery_jobs",
            "identities",
            "password_credentials",
            "password_recovery_tokens",
            "refresh_tokens",
            "sessions",
            "users",
        },
        "public": {
            "projects",
            "users",
            "external_repositories",
            "agents",
            "review_runs",
            "review_run_agents",
            "review_run_categories",
            "findings",
            "remediations",
            "pull_requests",
            "local_file_backups",
        },
    }
    actual_tables: dict[str, set[str]] = {}

    for table in Base.metadata.tables.values():
        if table.schema in expected_tables:
            actual_tables.setdefault(table.schema, set()).add(table.name)

    assert actual_tables == expected_tables


def test_private_tables_remain_outside_the_auth_and_public_schemas() -> None:
    assert Credential.__table__.schema == "private"
    assert AuditDeliveryJob.__table__.schema == "private"
    assert AuditDeliveryJob.__table__.c.canonical_json.nullable is False
    assert AuditDeliveryJob.__table__.c.event_hash.nullable is False


def test_agents_can_reference_only_owner_scoped_credentials() -> None:
    credential_id = Agent.__table__.c.credential_id

    assert credential_id.nullable
    assert any(
        constraint.name == "agents_owner_credential_fkey"
        and list(constraint.column_keys) == ["owner_id", "credential_id"]
        for constraint in Agent.__table__.foreign_key_constraints
    )


def test_generated_primary_keys_use_the_uuidv7_database_default() -> None:
    generated_models = (
        AuthUser,
        AuthIdentity,
        AuthSession,
        RefreshToken,
        EmailVerificationToken,
        PasswordRecoveryToken,
        Project,
        Credential,
        ExternalRepository,
        Agent,
        ReviewRun,
        Finding,
        Remediation,
        PullRequest,
        LocalFileBackup,
    )

    assert all(
        str(model.__table__.c.id.server_default.arg) == "public.uuidv7()"
        for model in generated_models
    )
