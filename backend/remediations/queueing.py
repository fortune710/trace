"""Strict identifier-only RabbitMQ contract for automatic remediation PRs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID


class RemediationPullRequestMessageInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RemediationPullRequestMessageV1:
    owner_id: UUID
    remediation_id: UUID
    idempotency_id: UUID
    version: int = 1

    def encode(self) -> bytes:
        return json.dumps(
            {
                "idempotency_id": str(self.idempotency_id),
                "owner_id": str(self.owner_id),
                "remediation_id": str(self.remediation_id),
                "version": self.version,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")

    @classmethod
    def decode(cls, body: bytes) -> RemediationPullRequestMessageV1:
        try:
            payload = json.loads(body)
            if (
                set(payload)
                != {
                    "idempotency_id",
                    "owner_id",
                    "remediation_id",
                    "version",
                }
                or payload["version"] != 1
            ):
                raise ValueError
            return cls(
                owner_id=UUID(payload["owner_id"]),
                remediation_id=UUID(payload["remediation_id"]),
                idempotency_id=UUID(payload["idempotency_id"]),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise RemediationPullRequestMessageInvalid(
                "Remediation pull-request message is invalid"
            ) from error


__all__ = [
    "RemediationPullRequestMessageInvalid",
    "RemediationPullRequestMessageV1",
]
