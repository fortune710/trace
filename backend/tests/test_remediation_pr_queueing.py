from uuid import uuid4

import pytest

from remediations.queueing import (
    RemediationPullRequestMessageInvalid,
    RemediationPullRequestMessageV1,
)


def test_remediation_pr_queue_message_round_trips_identifier_only_fields() -> None:
    message = RemediationPullRequestMessageV1(
        owner_id=uuid4(), remediation_id=uuid4(), idempotency_id=uuid4()
    )

    decoded = RemediationPullRequestMessageV1.decode(message.encode())

    assert decoded == message
    assert b"diff" not in message.encode()
    assert b"prompt" not in message.encode()


@pytest.mark.parametrize(
    "body",
    (
        b"{}",
        b'{"version": 2}',
        b'{"owner_id": "not-a-uuid", "remediation_id": "x", "idempotency_id": "x", "version": 1}',
    ),
)
def test_remediation_pr_queue_rejects_non_contract_messages(body: bytes) -> None:
    with pytest.raises(RemediationPullRequestMessageInvalid):
        RemediationPullRequestMessageV1.decode(body)
