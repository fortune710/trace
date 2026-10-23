from db import model_registry
from db.base import Base

EXPECTED_TABLES = {
    "auth.email_delivery_jobs",
    "auth.email_verification_tokens",
    "auth.identities",
    "auth.password_credentials",
    "auth.password_recovery_tokens",
    "auth.refresh_tokens",
    "auth.sessions",
    "auth.users",
    "private.audit_delivery_jobs",
    "private.credential_reencryption_items",
    "private.credential_reencryption_runs",
    "private.credentials",
    "public.agents",
    "public.external_repositories",
    "public.findings",
    "public.local_file_backups",
    "public.projects",
    "public.pull_requests",
    "public.remediations",
    "public.review_run_agents",
    "public.review_run_categories",
    "public.review_runs",
    "public.users",
}


def test_registry_imports_every_authoritative_table_once() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert len(Base.metadata.tables) == len(EXPECTED_TABLES)
    assert set(model_registry.__all__) == {
        "Agent",
        "AuditDeliveryJob",
        "AuthIdentity",
        "AuthSession",
        "AuthUser",
        "Credential",
        "CredentialReencryptionItem",
        "CredentialReencryptionRun",
        "EmailDeliveryJob",
        "EmailVerificationToken",
        "ExternalRepository",
        "Finding",
        "LocalFileBackup",
        "PasswordCredential",
        "PasswordRecoveryToken",
        "Project",
        "PullRequest",
        "RefreshToken",
        "Remediation",
        "ReviewRun",
        "ReviewRunAgent",
        "ReviewRunCategory",
        "User",
    }
