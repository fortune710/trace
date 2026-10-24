"""Safe review-dispatch message contract for the future outbox publisher."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID


class ReviewDispatchMessageInvalid(ValueError):
    """Raised when a queue message is not the approved identifier-only shape."""


@dataclass(frozen=True)
class ReviewDispatchMessageV1:
    """One selected-agent assignment awaiting future review execution."""

    review_id: UUID
    review_agent_id: UUID
    owner_id: UUID
    idempotency_id: UUID
    version: int = 1

    def encode(self) -> bytes:
        return json.dumps(
            {
                "idempotency_id": str(self.idempotency_id),
                "owner_id": str(self.owner_id),
                "review_agent_id": str(self.review_agent_id),
                "review_id": str(self.review_id),
                "version": self.version,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")

    @classmethod
    def decode(cls, body: bytes) -> ReviewDispatchMessageV1:
        try:
            payload = json.loads(body)
            if (
                set(payload)
                != {
                    "idempotency_id",
                    "owner_id",
                    "review_agent_id",
                    "review_id",
                    "version",
                }
                or payload["version"] != 1
            ):
                raise ValueError
            return cls(
                review_id=UUID(payload["review_id"]),
                review_agent_id=UUID(payload["review_agent_id"]),
                owner_id=UUID(payload["owner_id"]),
                idempotency_id=UUID(payload["idempotency_id"]),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ReviewDispatchMessageInvalid(
                "Review dispatch message is invalid"
            ) from error


__all__ = ["ReviewDispatchMessageInvalid", "ReviewDispatchMessageV1"]
