"""Durable, encrypted email jobs and the idempotent RabbitMQ consumer."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Engine

from auth.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    EncryptedCredential,
    VaultTransitCredentialCipher,
)
from auth.queueing import (
    EmailQueueMessage,
    QueueMessageInvalid,
    QueueUnavailable,
    RabbitMQEmailPublisher,
)
from auth.uuids import uuid7
from db.models import EmailDeliveryJob, EmailDeliveryKind, EmailDeliveryStatus

logger = logging.getLogger("trace.auth")
_PAYLOAD_PROVIDER = "email"


class EmailDeliveryError(RuntimeError):
    """Base class for email delivery failures."""


class RetryableEmailDeliveryError(EmailDeliveryError):
    """SMTP or transport error that may succeed after a bounded delay."""


class PermanentEmailDeliveryError(EmailDeliveryError):
    """A malformed destination or payload that must not be retried."""


class EmailSender(Protocol):
    def send(self, *, recipient: str, subject: str, body: str) -> None: ...


class DeliveryChannel(Protocol):
    def basic_ack(self, *, delivery_tag: int) -> object: ...

    def basic_nack(self, *, delivery_tag: int, requeue: bool) -> object: ...


@dataclass(frozen=True)
class EmailJob:
    id: UUID
    user_id: UUID
    kind: EmailDeliveryKind
    status: EmailDeliveryStatus
    encrypted_payload: EncryptedCredential
    attempt_count: int


class EmailJobStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(
        self,
        connection: sa.Connection,
        *,
        user_id: UUID,
        kind: EmailDeliveryKind,
        payload: dict[str, object],
        cipher: CredentialCipher | VaultTransitCredentialCipher,
    ) -> UUID:
        job_id = uuid7()
        encrypted = cipher.encrypt_json(
            payload,
            credential_id=job_id,
            owner_id=user_id,
            provider=_PAYLOAD_PROVIDER,
            credential_kind=kind.value,
        )
        connection.execute(
            sa.insert(EmailDeliveryJob).values(
                id=job_id,
                user_id=user_id,
                kind=kind,
                payload_ciphertext=encrypted.ciphertext,
                payload_nonce=encrypted.nonce,
                payload_key_version=encrypted.key_version,
                payload_aad_version=encrypted.aad_version,
                payload_encryption_provider=encrypted.encryption_provider,
                payload_key_reference=encrypted.key_reference,
            )
        )
        return job_id

    def get(self, job_id: UUID) -> EmailJob | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(EmailDeliveryJob).where(EmailDeliveryJob.id == job_id)
                )
                .mappings()
                .one_or_none()
            )
        return _row_to_job(row) if row is not None else None

    def mark_published(self, job_id: UUID) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(EmailDeliveryJob)
                .where(
                    EmailDeliveryJob.id == job_id,
                    EmailDeliveryJob.status == EmailDeliveryStatus.PENDING,
                )
                .values(published_at=sa.func.now(), updated_at=sa.func.now())
            )

    def pending_unpublished(self, *, limit: int = 100) -> list[UUID]:
        with self._engine.connect() as connection:
            return list(
                connection.execute(
                    sa.select(EmailDeliveryJob.id)
                    .where(
                        EmailDeliveryJob.status == EmailDeliveryStatus.PENDING,
                        EmailDeliveryJob.published_at.is_(None),
                    )
                    .order_by(EmailDeliveryJob.created_at)
                    .limit(limit)
                ).scalars()
            )

    def mark_sent(self, job_id: UUID) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(EmailDeliveryJob)
                .where(
                    EmailDeliveryJob.id == job_id,
                    EmailDeliveryJob.status == EmailDeliveryStatus.PENDING,
                )
                .values(
                    status=EmailDeliveryStatus.SENT,
                    sent_at=sa.func.now(),
                    updated_at=sa.func.now(),
                )
            )
        return result.rowcount == 1

    def schedule_retry(self, job_id: UUID, *, attempt_count: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(EmailDeliveryJob)
                .where(
                    EmailDeliveryJob.id == job_id,
                    EmailDeliveryJob.status == EmailDeliveryStatus.PENDING,
                )
                .values(attempt_count=attempt_count, updated_at=sa.func.now())
            )

    def mark_failed(self, job_id: UUID, *, reason: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(EmailDeliveryJob)
                .where(
                    EmailDeliveryJob.id == job_id,
                    EmailDeliveryJob.status == EmailDeliveryStatus.PENDING,
                )
                .values(
                    status=EmailDeliveryStatus.FAILED,
                    failure_reason=reason,
                    failed_at=sa.func.now(),
                    updated_at=sa.func.now(),
                )
            )


class EmailJobDispatcher:
    def __init__(self, store: EmailJobStore, publisher: RabbitMQEmailPublisher) -> None:
        self._store = store
        self._publisher = publisher

    def dispatch(self, job_id: UUID) -> bool:
        try:
            self._publisher.publish(EmailQueueMessage(job_id=job_id))
        except QueueUnavailable:
            logger.warning(
                "auth_email_dispatch_deferred",
                extra={
                    "auth": {
                        "event": "email_dispatch",
                        "reason": "broker_unavailable",
                        "job_id": str(job_id),
                    }
                },
            )
            return False
        self._store.mark_published(job_id)
        return True

    def dispatch_pending(self) -> int:
        dispatched = 0
        for job_id in self._store.pending_unpublished():
            if not self.dispatch(job_id):
                break
            dispatched += 1
        return dispatched


class SMTPEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        use_starttls: bool = False,
    ) -> None:
        if not host or not 0 < port < 65_536:
            raise ValueError("SMTP configuration is invalid")
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password
        self._use_starttls = use_starttls

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        if not recipient or "\n" in recipient or "\r" in recipient:
            raise PermanentEmailDeliveryError("Recipient is invalid")
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as client:
                if self._use_starttls:
                    client.starttls()
                if self._username and self._password:
                    client.login(self._username, self._password)
                client.send_message(message)
        except smtplib.SMTPRecipientsRefused as error:
            raise PermanentEmailDeliveryError("Recipient was rejected") from error
        except (smtplib.SMTPException, OSError) as error:
            raise RetryableEmailDeliveryError("SMTP delivery failed") from error


class EmailJobConsumer:
    def __init__(
        self,
        *,
        store: EmailJobStore,
        cipher: CredentialCipher | VaultTransitCredentialCipher,
        sender: EmailSender,
        publisher: RabbitMQEmailPublisher,
        max_retries: int,
    ) -> None:
        self._store = store
        self._cipher = cipher
        self._sender = sender
        self._publisher = publisher
        self._max_retries = max_retries

    def consume(
        self, *, delivery_tag: int, body: bytes, channel: DeliveryChannel
    ) -> None:
        """Process a delivery; only ack once the durable outcome is known."""
        try:
            message = EmailQueueMessage.decode(body)
        except QueueMessageInvalid:
            _nack(channel, delivery_tag)
            return
        job = self._store.get(message.job_id)
        if job is None or job.status in {
            EmailDeliveryStatus.SENT,
            EmailDeliveryStatus.FAILED,
        }:
            _ack(channel, delivery_tag)
            return
        if message.attempt != job.attempt_count:
            _ack(channel, delivery_tag)
            return

        try:
            payload = self._cipher.decrypt_json(
                job.encrypted_payload,
                credential_id=job.id,
                owner_id=job.user_id,
                provider=_PAYLOAD_PROVIDER,
                credential_kind=job.kind.value,
            )
            recipient, subject, body_text = _email_content(job.kind, payload)
            self._sender.send(recipient=recipient, subject=subject, body=body_text)
            self._store.mark_sent(job.id)
        except CredentialDecryptionError:
            self._store.mark_failed(job.id, reason="payload_invalid")
            _log_delivery("email_delivery", "failed", "payload_invalid", job)
            _nack(channel, delivery_tag)
            return
        except PermanentEmailDeliveryError:
            self._store.mark_failed(job.id, reason="recipient_rejected")
            _log_delivery("email_delivery", "failed", "recipient_rejected", job)
            _nack(channel, delivery_tag)
            return
        except RetryableEmailDeliveryError:
            self._retry_or_dead_letter(job, message, delivery_tag, channel)
            return
        _log_delivery("email_delivery", "sent", "delivered", job)
        _ack(channel, delivery_tag)

    def _retry_or_dead_letter(
        self,
        job: EmailJob,
        message: EmailQueueMessage,
        delivery_tag: int,
        channel: DeliveryChannel,
    ) -> None:
        next_attempt = message.attempt + 1
        if next_attempt > self._max_retries:
            self._store.mark_failed(job.id, reason="retry_limit_exceeded")
            _log_delivery("email_delivery", "failed", "retry_limit_exceeded", job)
            _nack(channel, delivery_tag)
            return
        try:
            self._publisher.publish(
                EmailQueueMessage(job_id=job.id, attempt=next_attempt),
                retry_index=message.attempt,
            )
        except QueueUnavailable:
            # Return the original message to its work queue. It is not acknowledged
            # until a durable retry publish confirmation has been received.
            _log_delivery(
                "email_delivery", "deferred", "retry_publish_unavailable", job
            )
            _nack(channel, delivery_tag, requeue=True)
            return
        self._store.schedule_retry(job.id, attempt_count=next_attempt)
        _log_delivery(
            "email_delivery",
            "retry_scheduled",
            "smtp_transient_failure",
            job,
            attempt=next_attempt,
        )
        _ack(channel, delivery_tag)


def _row_to_job(row: sa.RowMapping) -> EmailJob:
    return EmailJob(
        id=row["id"],
        user_id=row["user_id"],
        kind=EmailDeliveryKind(row["kind"]),
        status=EmailDeliveryStatus(row["status"]),
        encrypted_payload=EncryptedCredential(
            ciphertext=row["payload_ciphertext"],
            nonce=row["payload_nonce"],
            key_version=row["payload_key_version"],
            aad_version=row["payload_aad_version"],
            encryption_provider=row["payload_encryption_provider"],
            key_reference=row["payload_key_reference"],
        ),
        attempt_count=row["attempt_count"],
    )


def _email_content(
    kind: EmailDeliveryKind, payload: dict[str, object]
) -> tuple[str, str, str]:
    email = payload.get("email")
    token = payload.get("token")
    destination = payload.get("destination")
    if not isinstance(email, str) or not email:
        raise PermanentEmailDeliveryError("Email payload is invalid")
    if not isinstance(token, str) or not token:
        raise PermanentEmailDeliveryError("Email payload is invalid")
    if not isinstance(destination, str) or not destination:
        raise PermanentEmailDeliveryError("Email payload is invalid")
    if kind == EmailDeliveryKind.VERIFICATION:
        return (
            email,
            "Verify your Trace email",
            f"Verify your email: {destination.rstrip('/')}/auth/verify#token={quote(token, safe='')}",
        )
    return (
        email,
        "Reset your Trace password",
        f"Reset your password: {destination.rstrip('/')}/auth/reset-password#token={quote(token, safe='')}",
    )


def _ack(channel: DeliveryChannel, delivery_tag: int) -> None:
    channel.basic_ack(delivery_tag=delivery_tag)


def _nack(
    channel: DeliveryChannel, delivery_tag: int, *, requeue: bool = False
) -> None:
    channel.basic_nack(delivery_tag=delivery_tag, requeue=requeue)


def _log_delivery(
    event: str, outcome: str, reason: str, job: EmailJob, *, attempt: int | None = None
) -> None:
    logger.info(
        "auth_email_delivery",
        extra={
            "auth": {
                "event": event,
                "outcome": outcome,
                "reason": reason,
                "job_id": str(job.id),
                "attempt": job.attempt_count if attempt is None else attempt,
                "kind": job.kind.value,
            }
        },
    )
