"""Process entry point for publishing review-dispatch outbox rows."""

from __future__ import annotations

from audit.runtime import get_audit_recorder
from db.session import get_engine
from reviews.config import ReviewDispatchSettings
from reviews.dispatch import RabbitMQReviewPublisher, ReviewDispatchWorker


def main() -> None:
    settings = ReviewDispatchSettings()
    settings.validate_for_dispatch()
    engine = get_engine()
    worker = ReviewDispatchWorker(
        engine=engine,
        publisher=RabbitMQReviewPublisher(url=settings.rabbitmq_url or ""),
        audit_recorder=get_audit_recorder(),
        max_attempts=settings.max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
        processing_timeout_seconds=settings.processing_timeout_seconds,
    )
    worker.run_forever(poll_seconds=settings.poll_seconds)


if __name__ == "__main__":
    main()
