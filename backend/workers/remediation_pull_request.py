"""Process entry point for failed remediation pull-request retries."""

from __future__ import annotations

from audit.outbox import AuditRecorder
from auth.config import AuthSettings
from auth.credential_service import CredentialService
from auth.credentials import credential_cipher_from_settings
from db.session import get_engine
from external_repositories.service import RepositoryService
from remediations.pull_request_worker import RemediationPullRequestWorker
from remediations.service import RemediationPullRequestService


def main() -> None:
    settings = AuthSettings()
    engine = get_engine()
    audit_recorder = AuditRecorder(engine)
    repository_service = RepositoryService(
        engine=engine,
        credential_service=CredentialService(
            engine=engine,
            cipher=credential_cipher_from_settings(settings),
        ),
        settings=settings,
    )
    service = RemediationPullRequestService(
        engine,
        repository_service,
        audit_recorder,
    )
    RemediationPullRequestWorker(
        engine=engine,
        service=service,
        audit_recorder=audit_recorder,
    ).run_forever()


if __name__ == "__main__":
    main()
