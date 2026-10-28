"""Process entry point for remediation PR outbox publication."""

from audit.outbox import AuditRecorder
from db.session import get_engine
from remediations.config import RemediationPullRequestDispatchSettings
from remediations.dispatch import (
    RabbitMQRemediationPullRequestPublisher,
    RemediationPullRequestOutboxWorker,
)


def main() -> None:
    settings = RemediationPullRequestDispatchSettings()
    settings.validate_for_dispatch()
    engine = get_engine()
    RemediationPullRequestOutboxWorker(
        engine=engine,
        publisher=RabbitMQRemediationPullRequestPublisher(
            url=settings.rabbitmq_url or ""
        ),
        audit_recorder=AuditRecorder(engine),
        max_attempts=settings.max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
        processing_timeout_seconds=settings.processing_timeout_seconds,
    ).run_forever(poll_seconds=settings.poll_seconds)


if __name__ == "__main__":
    main()
