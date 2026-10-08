from db.base import Base
from db.types import RepositorySource

EXPECTED_COLUMNS = {
    "auth.users": {
        "id",
        "email",
        "status",
        "email_confirmed_at",
        "created_at",
        "updated_at",
        "deleted_at",
    },
    "auth.identities": {
        "id",
        "user_id",
        "provider",
        "provider_subject",
        "provider_metadata",
        "created_at",
        "updated_at",
    },
    "auth.password_credentials": {
        "user_id",
        "password_hash",
        "password_changed_at",
        "failed_attempt_count",
        "locked_until",
    },
    "auth.sessions": {
        "id",
        "user_id",
        "expires_at",
        "revoked_at",
        "created_at",
        "last_seen_at",
    },
    "auth.refresh_tokens": {
        "id",
        "session_id",
        "token_hash",
        "expires_at",
        "consumed_at",
        "revoked_at",
        "replaced_by_id",
        "created_at",
    },
    "auth.email_verification_tokens": {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "used_at",
        "created_at",
    },
    "auth.password_recovery_tokens": {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "used_at",
        "created_at",
    },
    "auth.email_delivery_jobs": {
        "id",
        "user_id",
        "kind",
        "status",
        "payload_ciphertext",
        "payload_nonce",
        "payload_key_version",
        "payload_aad_version",
        "payload_encryption_provider",
        "payload_key_reference",
        "attempt_count",
        "published_at",
        "sent_at",
        "failed_at",
        "failure_reason",
        "created_at",
        "updated_at",
    },
    "private.audit_delivery_jobs": {
        "event_id",
        "owner_id",
        "canonical_json",
        "event_hash",
        "status",
        "attempt_count",
        "next_attempt_at",
        "transaction_id",
        "transaction_hash",
        "failure_reason",
        "created_at",
        "updated_at",
    },
    "public.users": {"id", "display_name", "created_at", "updated_at"},
    "public.projects": {
        "id",
        "owner_id",
        "name",
        "source",
        "external_repository_id",
        "external_repository_connection_id",
        "repository_owner",
        "repository_name",
        "branch_name",
        "repository_visibility",
        "imported_at",
        "local_path_hash",
        "source_hash",
        "current_revision",
        "category",
        "auto_create_pull_requests",
        "created_at",
        "updated_at",
        "archived_at",
    },
    "private.credentials": {
        "id",
        "owner_id",
        "provider",
        "credential_kind",
        "ciphertext",
        "nonce",
        "key_version",
        "aad_version",
        "encryption_provider",
        "key_reference",
        "created_at",
        "updated_at",
        "mutation_version",
        "revoked_at",
    },
    "public.external_repositories": {
        "id",
        "owner_id",
        "source",
        "external_user_id",
        "credential_id",
        "connected_at",
        "revoked_at",
        "created_at",
        "updated_at",
    },
    "public.agents": {
        "id",
        "owner_id",
        "name",
        "personality",
        "review_category",
        "model_provider",
        "model_name",
        "credential_id",
        "skills",
        "fallback_order",
        "created_at",
        "updated_at",
        "disabled_at",
    },
    "public.review_runs": {
        "id",
        "owner_id",
        "project_id",
        "source_revision",
        "status",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
        "retry_version",
    },
    "public.review_run_agents": {
        "owner_id",
        "review_run_id",
        "agent_id",
        "status",
        "error_reason",
        "assigned_at",
        "started_at",
        "completed_at",
    },
    "public.review_run_categories": {"owner_id", "review_run_id", "category"},
    "public.findings": {
        "id",
        "owner_id",
        "review_run_id",
        "agent_id",
        "category",
        "severity",
        "title",
        "explanation",
        "evidence",
        "source_location",
        "recommendation",
        "status",
        "created_at",
        "updated_at",
    },
    "public.remediations": {
        "id",
        "owner_id",
        "project_id",
        "finding_id",
        "proposed_diff",
        "status",
        "approved_at",
        "created_at",
        "updated_at",
        "mutation_version",
    },
    "public.pull_requests": {
        "id",
        "owner_id",
        "remediation_id",
        "repository_url",
        "pull_request_number",
        "pull_request_url",
        "branch_name",
        "created_at",
        "updated_at",
    },
    "public.local_file_backups": {
        "id",
        "owner_id",
        "remediation_id",
        "file_path",
        "backup_path",
        "source_hash",
        "created_at",
        "updated_at",
    },
    "private.credential_reencryption_runs": {
        "id",
        "status",
        "encryption_provider",
        "target_key_reference",
        "target_key_version",
        "last_credential_id",
        "scanned_count",
        "rewrapped_count",
        "skipped_count",
        "failed_count",
        "last_error",
        "created_at",
        "updated_at",
        "completed_at",
    },
    "private.credential_reencryption_items": {
        "run_id",
        "credential_id",
        "status",
        "attempt_count",
        "last_error",
        "next_attempt_at",
        "updated_at",
    },
}


def test_table_columns_and_metadata_names_are_stable() -> None:
    assert set(Base.metadata.tables) == set(EXPECTED_COLUMNS)
    for table_name, columns in EXPECTED_COLUMNS.items():
        table = Base.metadata.tables[table_name]
        assert {column.name for column in table.c} == columns
        assert table.fullname == table_name


def test_primary_keys_foreign_keys_and_named_constraints_are_registered() -> None:
    projects = Base.metadata.tables["public.projects"]
    assert set(projects.primary_key.columns.keys()) == {"id"}
    assert {constraint.name for constraint in projects.constraints} >= {
        "projects_owner_id_id_key",
        "projects_source_reference_check",
    }
    assert {
        (foreign_key.parent.name, foreign_key.target_fullname)
        for foreign_key in projects.foreign_keys
    } >= {
        ("owner_id", "public.users.id"),
    }

    findings = Base.metadata.tables["public.findings"]
    assert {foreign_key.target_fullname for foreign_key in findings.foreign_keys} >= {
        "public.users.id",
        "public.review_run_agents.owner_id",
        "public.review_run_agents.review_run_id",
        "public.review_run_agents.agent_id",
    }


def test_indexes_and_enum_contracts_are_stable() -> None:
    expected_indexes = {
        "projects_owner_created_idx",
        "projects_owner_external_repository_key",
        "projects_owner_local_path_key",
        "credentials_active_owner_provider_kind_key",
        "external_repositories_owner_active_key",
        "agents_owner_created_idx",
        "review_runs_owner_created_idx",
        "findings_owner_created_idx",
        "remediations_owner_created_idx",
        "pull_requests_owner_created_idx",
        "local_file_backups_owner_created_idx",
    }
    actual_indexes = {
        index.name for table in Base.metadata.tables.values() for index in table.indexes
    }
    assert expected_indexes <= actual_indexes

    source_column = Base.metadata.tables["public.projects"].c.source
    assert source_column.type.enum_class is RepositorySource
    assert [member.value for member in RepositorySource] == ["github", "local"]
