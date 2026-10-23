"""Transaction-local PostgreSQL row-level-security context helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Engine

RLS_USER_SETTING = "trace.current_user_id"


@contextmanager
def principal_transaction(engine: Engine, user_id: UUID) -> Iterator[Connection]:
    """Run a transaction with a transaction-local authenticated user setting."""

    if not isinstance(user_id, UUID):
        raise TypeError("user_id must be a UUID")

    with engine.begin() as connection:
        connection.execute(
            sa.text("SELECT set_config(:setting_name, :setting_value, true)"),
            {
                "setting_name": RLS_USER_SETTING,
                "setting_value": str(user_id),
            },
        )
        yield connection


def set_principal_context(connection: Connection, user_id: UUID) -> None:
    """Set the RLS identity on an already-open transaction."""

    if not isinstance(user_id, UUID):
        raise TypeError("user_id must be a UUID")
    connection.execute(
        sa.text("SELECT set_config(:setting_name, :setting_value, true)"),
        {"setting_name": RLS_USER_SETTING, "setting_value": str(user_id)},
    )
